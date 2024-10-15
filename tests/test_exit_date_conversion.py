import unittest
from pymongo import MongoClient
from datetime import datetime

@unittest.skip("Manual test, run only when needed")
class TestExitDateConversion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Set up the MongoDB connection and test collection
        cls.client = MongoClient('mongodb+srv://user:pass@yourCluser')
        cls.db = cls.client['Api_Trader']
        
        # Define the collections to check for `Exit_Date` conversion
        cls.collections_to_check = ['closed_positions', 'open_positions', 'queue', 'canceled', 'rejected']


    def test_convert_exit_date_string_to_datetime(self):
        for collection_name in self.collections_to_check:
            collection = self.db[collection_name]
            print(f"Processing collection: {collection_name}")

            # Find documents where Exit_Date is a string
            string_exit_dates = collection.find({"Exit_Date": {"$type": "string"}})

            for doc in string_exit_dates:
                exit_date_str = doc['Exit_Date']
                try:
                    # Convert the string to datetime
                    exit_date_dt = datetime.fromisoformat(exit_date_str)

                    # Update the document with the correct datetime format
                    collection.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"Exit_Date": exit_date_dt}}
                    )

                    # Retrieve the updated document and assert the conversion was successful
                    updated_doc = collection.find_one({"_id": doc["_id"]})
                    self.assertIsInstance(updated_doc['Exit_Date'], datetime)

                except ValueError:
                    # If there's a ValueError, fail the test
                    self.fail(f"Invalid date format for document {doc['_id']} in {collection_name}: {exit_date_str}")

            print(f"Completed processing collection: {collection_name}")


    def test_convert_entry_date_string_to_datetime(self):
        for collection_name in self.collections_to_check:
            collection = self.db[collection_name]
            print(f"Processing collection: {collection_name}")

            # Find documents where Entry_Date is a string
            string_entry_dates = collection.find({"Entry_Date": {"$type": "string"}})

            for doc in string_entry_dates:
                entry_date_str = doc['Entry_Date']
                try:
                    # Convert the string to datetime
                    entry_date_dt = datetime.fromisoformat(entry_date_str)

                    # Update the document with the correct datetime format
                    collection.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"Entry_Date": entry_date_dt}}
                    )

                    # Retrieve the updated document and assert the conversion was successful
                    updated_doc = collection.find_one({"_id": doc["_id"]})
                    self.assertIsInstance(updated_doc['Entry_Date'], datetime)

                except ValueError:
                    # If there's a ValueError, fail the test
                    self.fail(f"Invalid date format for document {doc['_id']} in {collection_name}: {entry_date_str}")

            print(f"Completed processing collection: {collection_name}")


    def test_convert_date_string_to_datetime(self):
        for collection_name in self.collections_to_check:
            collection = self.db[collection_name]
            print(f"Processing collection: {collection_name}")

            # Find documents where Date is a string
            string_dates = collection.find({"Date": {"$type": "string"}})

            for doc in string_dates:
                date_str = doc['Date']
                try:
                    # Convert the string to datetime
                    date_dt = datetime.fromisoformat(date_str)

                    # Update the document with the correct datetime format
                    collection.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"Date": date_dt}}
                    )

                    # Retrieve the updated document and assert the conversion was successful
                    updated_doc = collection.find_one({"_id": doc["_id"]})
                    self.assertIsInstance(updated_doc['Date'], datetime)

                except ValueError:
                    # If there's a ValueError, fail the test
                    self.fail(f"Invalid date format for document {doc['_id']} in {collection_name}: {date_str}")

            print(f"Completed processing collection: {collection_name}")


    @classmethod
    def tearDownClass(cls):
        # Optionally, clean up if needed (e.g., restoring the data to the original state)
        cls.client.close()

# If you run this script directly, it will execute the test
if __name__ == '__main__':
    unittest.main()
