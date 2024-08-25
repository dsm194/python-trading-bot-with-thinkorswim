# imports
from assets.helper_functions import getDatetime
from dotenv import load_dotenv
from pathlib import Path
import os

from schwab.orders.common import OrderType, OrderStrategyType, EquityInstruction, Duration, Session, one_cancels_other, first_triggers_second
from schwab.orders.generic import OrderBuilder
from schwab.orders.equities import equity_buy_limit, equity_sell_limit
from schwab.orders.options import option_buy_to_open_limit, option_sell_to_close_limit

THIS_FOLDER = os.path.dirname(os.path.abspath(__file__))

path = Path(THIS_FOLDER)

load_dotenv(dotenv_path=f"{path.parent}/config.env")

BUY_PRICE = os.getenv('BUY_PRICE')
SELL_PRICE = os.getenv('SELL_PRICE')
TAKE_PROFIT_PERCENTAGE = float(os.getenv('TAKE_PROFIT_PERCENTAGE'))
STOP_LOSS_PERCENTAGE = float(os.getenv('STOP_LOSS_PERCENTAGE'))

# Define the AssetType enum manually
class AssetType:
    EQUITY = "EQUITY"
    OPTION = "OPTION"

class OrderBuilderWrapper:

    def __init__(self):

        self.obj = {
            "Symbol": None,
            "Qty": None,
            "Position_Size": None,
            "Strategy": None,
            "Trader": self.user["Name"],
            "Order_ID": None,
            "Order_Status": None,
            "Side": None,
            "Asset_Type": None,
            "Account_ID": self.account_id,
            "Position_Type": None,
            "Direction": None
        }

    def standardOrder(self, trade_data, strategy_object, direction, OCOorder=False):

        order = None
        symbol = trade_data["Symbol"]
        side = trade_data["Side"]
        strategy = trade_data["Strategy"]
        asset_type = AssetType.OPTION if "Pre_Symbol" in trade_data else AssetType.EQUITY

        ##############################################################

        # MONGO OBJECT
        self.obj.update({
            "Symbol": symbol,
            "Strategy": strategy,
            "Side": side,
            "Asset_Type": asset_type,
            "Position_Type": strategy_object["Position_Type"],
            "Order_Type": strategy_object["Order_Type"],
            "Direction": direction
        })

        ##############################################################

        # IF OPTION
        if asset_type == AssetType.OPTION:
            self.obj.update({
                "Pre_Symbol": trade_data["Pre_Symbol"],
                "Exp_Date": trade_data["Exp_Date"],
                "Option_Type": trade_data["Option_Type"]
            })

       # GET QUOTE FOR SYMBOL
        resp = self.tdameritrade.getQuote(symbol if asset_type == AssetType.EQUITY else trade_data["Pre_Symbol"])

        price = float(resp[symbol if asset_type == AssetType.EQUITY else trade_data["Pre_Symbol"]]['quote'][BUY_PRICE]) if side in ["BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"] else float(resp[symbol if asset_type == AssetType.EQUITY else trade_data["Pre_Symbol"]]['quote'][SELL_PRICE])

        # OCO ORDER NEEDS TO USE ASK PRICE FOR ISSUE WITH THE ORDER BEING TERMINATED UPON BEING PLACED
        if OCOorder:
            price = float(resp[symbol if asset_type == AssetType.EQUITY else trade_data["Pre_Symbol"]]['quote'][SELL_PRICE])

        price = round(price, 2) if price >= 1 else round(price, 4)
        priceAsString = str(price)

        # IF OPENING A POSITION
        if direction == "OPEN POSITION":

            position_size = int(strategy_object["Position_Size"])
            shares = int(position_size / price) if asset_type == AssetType.EQUITY else int((position_size / 100) / price)

            if strategy_object["Active"] and shares > 0:
                if asset_type == AssetType.EQUITY:
                    order = equity_buy_limit(symbol=trade_data["Symbol"], quantity=shares, price=priceAsString)
                else:
                    order = option_buy_to_open_limit(symbol=trade_data["Pre_Symbol"], quantity=shares, price=priceAsString)
                    
                self.obj.update({
                    "Qty": shares,
                    "Position_Size": position_size,
                    "Entry_Price": price,
                    "Entry_Date": getDatetime()
                })
            else:
                self.logger.warning(f"{side} ORDER STOPPED: STRATEGY STATUS - {strategy_object['Active']} SHARES - {shares}")
                return None, None

        # IF CLOSING A POSITION
        elif direction == "CLOSE POSITION":

            if asset_type == AssetType.EQUITY:
                order = equity_sell_limit(symbol=trade_data["Symbol"], quantity=trade_data["Qty"], price=priceAsString)
            else:
                order = option_sell_to_close_limit(symbol=trade_data["Pre_Symbol"], quantity=trade_data["Qty"], price=priceAsString)

            self.obj.update({
                "Entry_Price": trade_data["Entry_Price"],
                "Entry_Date": trade_data["Entry_Date"],
                "Exit_Price": price,
                "Exit_Date": getDatetime(),
                "Qty": trade_data["Qty"],
                "Position_Size": trade_data["Position_Size"]
            })
        ############################################################################

        return order, self.obj

    def OCOorder(self, trade_data, strategy_object, direction):

        parent_order, obj = self.standardOrder(trade_data, strategy_object, direction, OCOorder=True)
        asset_type = AssetType.OPTION if "Pre_Symbol" in trade_data else AssetType.EQUITY
        side = trade_data["Side"]
        parentOrderPriceAsFloat = float(parent_order._price)

        # GET THE INVERSE OF THE SIDE
        instruction = {
            "BUY_TO_OPEN": EquityInstruction.SELL,
            "BUY": EquityInstruction.SELL,
            "SELL": EquityInstruction.BUY,
            "SELL_TO_OPEN": EquityInstruction.BUY,
            "BUY_TO_COVER": EquityInstruction.SELL_SHORT,
            "SELL_SHORT": EquityInstruction.BUY_TO_COVER
        }[side]

       # Create take profit order
        take_profit_order_builder = (OrderBuilder()
            .set_order_type(OrderType.LIMIT)
            .set_session(Session.NORMAL)
            .set_duration(Duration.GOOD_TILL_CANCEL)
            .set_order_strategy_type(OrderStrategyType.SINGLE))
        take_profit_order_builder_price = parentOrderPriceAsFloat * TAKE_PROFIT_PERCENTAGE
        take_profit_order_builder_price = round(take_profit_order_builder_price, 2) if take_profit_order_builder_price >= 1 else round(take_profit_order_builder_price, 4)
        take_profit_order_builder.set_price(str(take_profit_order_builder_price))
        
        if asset_type == AssetType.EQUITY:
            take_profit_order_builder.add_equity_leg(instruction=instruction, symbol=trade_data["Symbol"], quantity=obj["Qty"])
        else:
            take_profit_order_builder.add_option_leg(instruction=instruction, symbol=trade_data["Pre_Symbol"], quantity=obj["Qty"])

        # Create stop loss order
        stop_loss_order_builder = (OrderBuilder()
            .set_order_type(OrderType.STOP)
            .set_session(Session.NORMAL)
            .set_duration(Duration.GOOD_TILL_CANCEL)
            .set_order_strategy_type(OrderStrategyType.SINGLE))
        stop_loss_order_builder_price = parentOrderPriceAsFloat * STOP_LOSS_PERCENTAGE
        stop_loss_order_builder_price = round(stop_loss_order_builder_price, 2) if stop_loss_order_builder_price >= 1 else round(stop_loss_order_builder_price, 4)
        stop_loss_order_builder.set_stop_price(str(stop_loss_order_builder_price))

        if asset_type == AssetType.EQUITY:
            stop_loss_order_builder.add_equity_leg(instruction=instruction, symbol=trade_data["Symbol"], quantity=obj["Qty"])
        else:
            stop_loss_order_builder.add_option_leg(instruction=instruction, symbol=trade_data["Pre_Symbol"], quantity=obj["Qty"])

        # Use one_cancels_other to create OCO order
        oco_order = one_cancels_other(take_profit_order_builder.build(), stop_loss_order_builder.build()).build()
        trigger_order = first_triggers_second(parent_order, oco_order)

        obj["childOrderStrategies"] = [oco_order]

        return trigger_order, obj
