# imports
from datetime import datetime, timedelta
import urllib.parse as up
import time
import httpx
import requests
from assets.helper_functions import modifiedAccountID
from assets.exception_handler import exception_handler
from schwab.auth import easy_client
from schwab.auth import client_from_manual_flow
from schwab.auth import client_from_login_flow
from schwab.auth import client_from_token_file
from schwab.client.base import BaseClient as schwabBaseClient
import os
from dotenv import load_dotenv

load_dotenv(dotenv_path="config.env")

API_KEY = os.getenv("API_KEY")
APP_SECRET = os.getenv("APP_SECRET")
CALLBACK_URL = os.getenv("CALLBACK_URL")

class TDAmeritrade:

    def __init__(self, mongo, user, account_id, logger, push_notification):

        self.user = user

        self.account_id = account_id

        self.logger = logger

        self.users = mongo.users

        self.push_notification = push_notification

        self.no_go_token_sent = False

        self.client_id = self.user["ClientID"]

        self.header = {}

        self.terminate = False

        self.invalid_count = 0

        self.client = {}

    @exception_handler
    def initialConnect(self):

        self.logger.info(
            f"CONNECTING {self.user['Name']} TO TDAMERITRADE ({modifiedAccountID(self.account_id)})", extra={'log': False})

        isValid = self.checkTokenValidity()

        if isValid:

            self.logger.info(
                f"CONNECTED {self.user['Name']} TO TDAMERITRADE ({modifiedAccountID(self.account_id)})", extra={'log': False})

            return True

        else:

            self.logger.error(
                f"FAILED TO CONNECT {self.user['Name']} TO TDAMERITRADE ({self.account_id})", extra={'log': False})

            return False

    @exception_handler
    def checkTokenValidity(self):
        """ METHOD CHECKS IF ACCESS TOKEN IS VALID

        Returns:
            [boolean]: TRUE IF SUCCESSFUL, FALSE IF ERROR
        """

        # GET USER DATA
        user = self.users.find_one({"Name": self.user["Name"]})
        token_path = user["Accounts"][self.account_id]['token_path']
        if os.path.isfile(token_path):
            c = client_from_token_file(token_path, API_KEY, APP_SECRET)
        else:
            self.logger.warning('Failed to find token file \'%s\'', token_path)
            c = client_from_manual_flow(API_KEY, APP_SECRET, CALLBACK_URL, token_path)

        if c:
            self.client = c

            # ADD NEW TOKEN DATA TO USER DATA IN DB
            self.users.update_one({"Name": self.user["Name"]}, {
                "$set": {f"{self.account_id}.refresh_exp_date": (datetime.now().replace(
                    microsecond=0) + timedelta(days=90)).strftime("%Y-%m-%d")}})

        #         self.header.update({
        #             "Authorization": f"Bearer {token['access_token']}"})

        else:

            return False

        return True

    @exception_handler
    def sendRequest(self, url, method="GET", data=None):
        """ METHOD SENDS ALL REQUESTS FOR METHODS BELOW.

        Args:
            url ([str]): URL for the particular API
            method (str, optional): GET, POST, PUT, DELETE. Defaults to "GET".
            data ([dict], optional): ONLY IF POST REQUEST. Defaults to None.

        Returns:
            [json]: RESPONSE DATA
        """

        isValid = self.checkTokenValidity()

        if isValid:

            if method == "GET":

                resp = requests.get(url, headers=self.header)

                return resp.json()

            elif method == "POST":

                resp = requests.post(url, headers=self.header, json=data)

                return resp

            elif method == "PATCH":

                resp = requests.patch(url, headers=self.header, json=data)

                return resp

            elif method == "PUT":

                resp = requests.put(url, headers=self.header, json=data)

                return resp

            elif method == "DELETE":

                resp = requests.delete(url, headers=self.header)

                return resp

        else:

            return

    def getAccount(self):
        """ METHOD GET ACCOUNT DATA

        Returns:
            [json]: ACCOUNT DATA
        """

        # fields = up.quote("positions,orders")

        # url = f"https://api.tdameritrade.com/v1/accounts/{self.account_id}?fields={fields}"

        # return self.sendRequest(url)

        isValid = self.checkTokenValidity()

        if isValid:
            resp = self.client.get_account_numbers()
            if resp.status_code == httpx.codes.OK:
                # The response has the following structure. If you have multiple linked
                # accounts, you'll need to inspect this object to find the hash you want:
                # [
                #    {
                #        "accountNumber": "123456789",
                #        "hashValue":"123ABCXYZ"
                #    }
                #]
                account_hash = resp.json()[0]['hashValue']
                return self.client.get_account(account_hash).json()
            else:
                return
        else:
            return

    def placeTDAOrder(self, data):
        """ METHOD PLACES ORDER

        Args:
            data ([dict]): ORDER DATA

        Returns:
            [json]: ORDER RESPONSE INFO. USED TO RETRIEVE ORDER ID.
        """

        url = f"https://api.tdameritrade.com/v1/accounts/{self.account_id}/orders"

        # return self.sendRequest(url, method="POST", data=data)

        isValid = self.checkTokenValidity()

        if isValid:
            resp = self.client.get_account_numbers()
            if resp.status_code == httpx.codes.OK:
                # The response has the following structure. If you have multiple linked
                # accounts, you'll need to inspect this object to find the hash you want:
                # [
                #    {
                #        "accountNumber": "123456789",
                #        "hashValue":"123ABCXYZ"
                #    }
                #]
                account_hash = resp.json()[0]['hashValue']
                return self.client.place_order(account_hash, data)
            else:
                return
        else:
            return

    def getBuyingPower(self):
        """ METHOD GETS BUYING POWER

        Returns:
            [json]: BUYING POWER
        """

        account = self.getAccount()

        buying_power = account["securitiesAccount"]["initialBalances"]["cashAvailableForTrading"]

        return float(buying_power)

    def getQuote(self, symbol):
        """ METHOD GETS MOST RECENT QUOTE FOR STOCK

        Args:
            symbol ([str]): STOCK SYMBOL

        Returns:
            [json]: STOCK QUOTE
        """

        # url = f"https://api.tdameritrade.com/v1/marketdata/{symbol}/quotes"

        # return self.sendRequest(url)

        isValid = self.checkTokenValidity()

        if symbol == None or symbol == '':
            self.logger.warning('Symbol in getQuote was empty \'%s\'', symbol)
            isValid = False

        if isValid:
            if "/" in symbol:
                return self.client.get_quotes(symbol).json()
            else:
                return self.client.get_quote(symbol).json()
        else:
            return

    def getQuotes(self, symbols):
        """ METHOD GETS STOCK QUOTES FOR MULTIPLE STOCK IN ONE CALL.

        Args:
            symbols ([list]): LIST OF SYMBOLS

        Returns:
            [json]: ALL SYMBOLS STOCK DATA
        """

        # join_ = ",".join(symbols)

        # seperated_values = up.quote(join_)

        # url = f"https://api.tdameritrade.com/v1/marketdata/quotes?symbol={seperated_values}"

        # return self.sendRequest(url)

        isValid = self.checkTokenValidity()

        if isValid:
            return self.client.get_quotes(symbols).json()
        else:
            return

    def getSpecificOrder(self, id):
        """ METHOD GETS A SPECIFIC ORDER INFO

        Args:
            id ([int]): ORDER ID FOR ORDER

        Returns:
            [json]: ORDER DATA
        """

        # url = f"https://api.tdameritrade.com/v1/accounts/{self.account_id}/orders/{id}"

        # return self.sendRequest(url)

        isValid = self.checkTokenValidity()

        if isValid:
            resp = self.client.get_account_numbers()
            if resp.status_code == httpx.codes.OK:
                # The response has the following structure. If you have multiple linked
                # accounts, you'll need to inspect this object to find the hash you want:
                # [
                #    {
                #        "accountNumber": "123456789",
                #        "hashValue":"123ABCXYZ"
                #    }
                #]
                account_hash = resp.json()[0]['hashValue']
                return self.client.get_order(id, account_hash).json()
            else:
                return
        else:
            return

    def cancelOrder(self, id):
        """ METHOD CANCELS ORDER

        Args:
            id ([int]): ORDER ID FOR ORDER

        Returns:
            [json]: RESPONSE. LOOKING FOR STATUS CODE 200,201
        """

        url = f"https://api.tdameritrade.com/v1/accounts/{self.account_id}/orders/{id}"

        # return self.sendRequest(url, method="DELETE")

        isValid = self.checkTokenValidity()

        if isValid:
            resp = self.client.get_account_numbers()
            if resp.status_code == httpx.codes.OK:
                # The response has the following structure. If you have multiple linked
                # accounts, you'll need to inspect this object to find the hash you want:
                # [
                #    {
                #        "accountNumber": "123456789",
                #        "hashValue":"123ABCXYZ"
                #    }
                #]
                account_hash = resp.json()[0]['hashValue']
                return self.client.cancel_order(id, account_hash).json()
            else:
                return
        else:
            return
        
    def getMarketHours(self, markets=None, *, date=None):
        isValid = self.checkTokenValidity()

        if isValid:

            # If no market is provided, get all the enum values as a list
            if markets is None:
                markets = [market for market in schwabBaseClient.MarketHours.Market]

            return self.client.get_market_hours(markets=markets, date=date).json()
        else:
            return
