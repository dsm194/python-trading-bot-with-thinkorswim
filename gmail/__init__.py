##################################################################################
# GMAIL CLASS ####################################################################
# Handles email auth and messages ################################################

# imports
import asyncio
from zoneinfo import ZoneInfo
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import os.path
import os
from datetime import datetime
import re

THIS_FOLDER = os.path.dirname(os.path.abspath(__file__))


class Gmail:

    def __init__(self, logger):

        self.logger = logger

        self.SCOPES = ["https://mail.google.com/"]

        self.creds = None

        self.service = None

        self.token_file = f"{THIS_FOLDER}/creds/token.json"

        self.creds_file = f"{THIS_FOLDER}/creds/credentials.json"

    def connect(self):
        """ METHOD SETS ATTRIBUTES AND CONNECTS TO GMAIL API

        Args:
            mongo ([object]): MONGODB OBJECT
            logger ([object]): LOGGER OBJECT
        """

        try:

            self.logger.info("CONNECTING TO GMAIL...", extra={'log': False})

            if os.path.exists(self.token_file):

                with open(self.token_file, 'r') as token:

                    self.creds = Credentials.from_authorized_user_file(
                        self.token_file, self.SCOPES)

            if not self.creds:

                flow = InstalledAppFlow.from_client_secrets_file(
                    self.creds_file, self.SCOPES)

                self.creds = flow.run_local_server(port=0)

            elif self.creds and self.creds.expired and self.creds.refresh_token:

                self.creds.refresh(Request())

            if self.creds != None:

                # Save the credentials for the next run
                with open(self.token_file, 'w') as token:

                    token.write(self.creds.to_json())

                self.service = build('gmail', 'v1', credentials=self.creds)

                self.logger.info("CONNECTED TO GMAIL!\n", extra={'log': False})

                return True

            else:

                raise Exception("Creds Not Found!")

        except Exception as e:

            self.logger.error(
                f"FAILED TO CONNECT TO GMAIL! - {e}\n", extra={'log': False})

            return False

    def translate_option_symbol(self, symbol: str) -> str:
        """
        Reverses the option symbol from '.WM241011C210' to 'WM    241011C00210000'.
        
        Args:
        symbol (str): The input symbol in the format '.WM241011C210'

        Returns:
        str: The symbol formatted with padding and an 8-digit strike price like 'WM    241011C00210000'
        """
        
        # Regex pattern to extract components
        pattern = r'\.(\w+)(\d{6})([CP])(\d+\.?\d*)'

        match = re.match(pattern, symbol)

        if not match:
            raise ValueError("The symbol format is not valid")
        
        # Extract components
        underlying = match.group(1)
        expiration = match.group(2)
        option_type_char = match.group(3)
        strike_price = match.group(4)

        # Convert the strike price to 8-digit format (e.g., '210' becomes '00210000')
        strike_price_numeric = float(strike_price)
        strike_price_formatted = f'{int(strike_price_numeric * 1000):08d}'  # Multiply by 1000 and format as an 8-digit number
        
        # Format the expiration date
        year = expiration[:2]
        month = expiration[2:4]
        day = expiration[4:6]
        expiration_date = datetime.strptime(f"{year}-{month}-{day}", "%y-%m-%d")

        # Determine option type (CALL/PUT)
        option_type = "CALL" if option_type_char == "C" else "PUT"

        # Format the translated symbol (e.g., 'WM    241011C00210000')
        pre_symbol = f"{underlying.ljust(6)}{expiration}{option_type_char}{strike_price_formatted}"

        return underlying, pre_symbol, expiration_date, option_type


    def extractSymbolsFromEmails(self, payloads):
        """ METHOD TAKES SUBJECT LINES OF THE EMAILS WITH THE SYMBOLS AND SCANNER NAMES AND EXTRACTS THE NEEDED THE INFO FROM THEM.
            NEEDED INFO: Symbol, Strategy, Side(Buy/Sell), Account ID

        Args:
            payloads ([list]): LIST OF EMAIL CONTENT

        Returns:
            [dict]: LIST OF EXTRACTED EMAIL CONTENT
        """

        trade_data = []

        # Alert: New Symbol: ABC was added to LinRegEMA_v2, BUY
        # Alert: New Symbol: ABC was added to LinRegEMA_v2, BUY

        for payload in payloads:

            try:

                separate = payload.split(":")

                # Check if the split yields at least 3 parts
                if len(separate) < 3:
                    self.logger.warning(f"{__class__.__name__} - Email Format Issue: {payload}")
                    continue  # Skip to the next payload if the format is invalid

                if len(separate) > 1:

                    contains = ["were added to", "was added to"]

                    for i in contains:

                        if i in separate[2]:

                            sep = separate[2].split(i)

                            symbols = sep[0].strip().split(",")

                            strategy, side = sep[1].strip().split(",")

                            for symbol in symbols:

                                symbol = symbol.strip()

                                if strategy != "" and side != "":

                                    obj = {
                                        "Symbol": symbol,
                                        "Side": side.replace(".", " ").upper().strip(),
                                        "Strategy": strategy.replace(".", " ").upper().strip(),
                                        "Asset_Type": "EQUITY"
                                    }

                                    # IF THIS IS AN OPTION
                                    if "." in symbol:

                                        symbol, pre_symbol, exp_date, option_type = self.translate_option_symbol(
                                            symbol)

                                        obj["Symbol"] = symbol

                                        obj["Pre_Symbol"] = pre_symbol

                                        obj["Exp_Date"] = exp_date

                                        obj["Option_Type"] = option_type

                                        obj["Asset_Type"] = "OPTION"

                                    # CHECK TO SEE IF ASSET TYPE AND SIDE ARE A LOGICAL MATCH
                                    if side.replace(".", " ").upper().strip() in ["SELL", "BUY"] and obj["Asset_Type"] == "EQUITY" or side.replace(".", " ").upper().strip() in ["SELL", "SELL_TO_CLOSE", "SELL_TO_OPEN", "BUY", "BUY_TO_CLOSE", "BUY_TO_OPEN"] and obj["Asset_Type"] == "OPTION":

                                        trade_data.append(obj)

                                    else:

                                        self.logger.warning(
                                            f"{__class__.__name__} - ILLOGICAL MATCH - SIDE: {side.upper().strip()} / ASSET TYPE: {obj['Asset_Type']}")

                                else:

                                    self.logger.warning(
                                        f"{__class__.__name__} - MISSING FIELDS FOR STRATEGY {strategy}")

                            break

                    self.logger.info(
                        f"New Email: {payload}", extra={'log': False})

            except IndexError:

                pass

            except ValueError as e:

                self.logger.warning(
                    f"{__class__.__name__} - Email Format Issue: {payload}")

            except Exception as e:

                self.logger.error(f"{__class__.__name__} - {e}")

        return trade_data

    # def getEmails(self):
    #     """ METHOD RETRIEVES EMAILS FROM INBOX, ADDS EMAIL TO TRASH FOLDER, AND ADD THEIR CONTENT TO payloads LIST TO BE EXTRACTED.

    #     Returns:
    #         [dict]: LIST RETURNED FROM extractSymbolsFromEmails METHOD
    #     """

    #     def convert_to_utc_with_timezone(local_hour, local_minute, timezone_str):
    #         """Convert local time to UTC based on a given timezone."""
    #         local_tz = ZoneInfo(timezone_str)
    #         # Create a local datetime object
    #         local_dt = datetime.now(local_tz).replace(
    #             hour=local_hour, minute=local_minute, second=0, microsecond=0
    #         )
    #         # Convert to UTC
    #         utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
    #         return utc_dt
        
    #     payloads = []

    #     # Convert the local time range to UTC
    #     start_time_utc = convert_to_utc_with_timezone(6, 31, "PST8PDT")
    #     end_time_utc = convert_to_utc_with_timezone(12, 59, "PST8PDT")
        
    #     # Gmail API requires RFC3339 format
    #     query = f'after:{int(start_time_utc.timestamp())} before:{int(end_time_utc.timestamp())}'    

    #     try:

    #         # GETS LIST OF ALL EMAILS, filtered to standard market hours
    #         results = self.service.users().messages().list(userId='me', q=query).execute()

    #         if results['resultSizeEstimate'] != 0:

    #             # {'id': '173da9a232284f0f', 'threadId': '173da9a232284f0f'}
    #             for message in results["messages"]:

    #                 result = self.service.users().messages().get(
    #                     id=message["id"], userId="me", format="metadata").execute()

    #                 for payload in result['payload']["headers"]:

    #                     if payload["name"] == "Subject":

    #                         payloads.append(payload["value"].strip())

    #                 # MOVE EMAIL TO TRASH FOLDER
    #                 self.service.users().messages().trash(
    #                     userId='me', id=message["id"]).execute()

    #     except Exception as e:

    #         self.logger.error(f"{__class__.__name__} - {e}")

    #     finally:

    #         return self.extractSymbolsFromEmails(payloads)

    async def getEmails(self):
        """
        Retrieves emails from the inbox within a specific time range, processes their content, and moves them to the trash.
        
        Returns:
            list: Extracted symbols from email subjects.
        """
        payloads = []

        def convert_to_utc_with_timezone(local_hour, local_minute, timezone_str):
            """Convert local time to UTC based on a given timezone."""
            local_tz = ZoneInfo(timezone_str)
            # Create a local datetime object
            local_dt = datetime.now(local_tz).replace(
                hour=local_hour, minute=local_minute, second=0, microsecond=0
            )
            # Convert to UTC
            utc_dt = local_dt.astimezone(ZoneInfo("UTC"))
            return utc_dt

        # Convert the local time range to UTC
        start_time_utc = convert_to_utc_with_timezone(6, 31, "PST8PDT")
        end_time_utc = convert_to_utc_with_timezone(12, 59, "PST8PDT")

        # Gmail API requires RFC3339 format
        query = f'after:{int(start_time_utc.timestamp())} before:{int(end_time_utc.timestamp())}'    

        try:
            # Get the list of all emails within the time range
            results = await self._fetch_email_list(query)

            if results.get('resultSizeEstimate', 0) > 0:
                # Iterate over each message and process it
                for message in results.get("messages", []):
                    subject = await self._process_email(message["id"])
                    if subject:
                        payloads.append(subject)

                    # Move the email to the trash
                    await self._move_to_trash(message["id"])
            else:
                self.logger.info("No emails found in the specified time range.")
        except Exception as e:
            self.logger.error(f"Error in getEmails: {e}")
        finally:
            # Extract symbols from email subjects and return the result
            return self.extractSymbolsFromEmails(payloads)

    # Helper Methods
    async def _fetch_email_list(self, query):
        """
        Fetch the list of emails from the inbox asynchronously with a query filter.

        Args:
            query (str): Gmail API query string to filter emails.

        Returns:
            dict: The API response containing email metadata.
        """
        try:
            request = self.service.users().messages().list(userId='me', q=query)
            return await asyncio.to_thread(request.execute)
        except Exception as e:
            self.logger.error(f"Error fetching email list: {e}")
            return {}


    async def _process_email(self, email_id):
        """
        Fetch the email details and extract the subject.

        Args:
            email_id (str): The ID of the email to process.

        Returns:
            str: The subject of the email, or None if not found.
        """
        try:
            request = self.service.users().messages().get(
                id=email_id, userId="me", format="metadata"
            )
            result = await asyncio.to_thread(request.execute)

            # Extract subject from headers
            headers = result.get('payload', {}).get("headers", [])
            for header in headers:
                if header.get("name") == "Subject":
                    return header.get("value", "").strip()
        except Exception as e:
            self.logger.error(f"Error processing email {email_id}: {e}")
        return None

    async def _move_to_trash(self, email_id):
        """
        Move an email to the trash folder.

        Args:
            email_id (str): The ID of the email to move.
        """
        try:
            request = self.service.users().messages().trash(userId='me', id=email_id)
            await asyncio.to_thread(request.execute)
            self.logger.info(f"Email {email_id} moved to trash.")
        except Exception as e:
            self.logger.error(f"Error moving email {email_id} to trash: {e}")
