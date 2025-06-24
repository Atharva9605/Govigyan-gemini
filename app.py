from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import os
from datetime import datetime
import json
import logging
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

app = Flask(__name__)
# Configure CORS to allow requests from your frontend
CORS(app, resources={r"/*": {"origins": ["http://localhost:3000", "https://your-deployed-frontend.com"],
                             "methods": ["GET", "POST", "OPTIONS"],
                             "allow_headers": ["Content-Type"]}})

# Configure logging to write to 'app.log' file
# Setting level to DEBUG to capture more detailed logs
logging.basicConfig(level=logging.DEBUG, filename='app.log', format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database connection parameters from environment variables
DB_PARAMS = {
    'dbname': os.getenv('DB_NAME', 'your_db'),
    'user': os.getenv('DB_USER', 'your_user'),
    'password': os.getenv('DB_PASSWORD', 'your_password'),
    'host': os.getenv('DB_HOST', 'your_host'),
    'port': os.getenv('DB_PORT', '5432')
}

# Google Sheets API setup
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

try:
    # Get the value of GOOGLE_CREDS from environment variables
    google_creds_value = os.getenv('GOOGLE_CREDS')

    if google_creds_value:
        try:
            # Attempt to parse GOOGLE_CREDS value as JSON
            creds_info = json.loads(google_creds_value)
            creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
            logger.info("Google Sheets API initialized successfully using JSON from GOOGLE_CREDS environment variable.")
        except json.JSONDecodeError:
            # If parsing as JSON fails, treat it as a file path
            logger.warning("GOOGLE_CREDS environment variable is not valid JSON. Attempting to load as file path.")
            creds = Credentials.from_service_account_file(google_creds_value, scopes=SCOPES)
            logger.info("Google Sheets API initialized successfully using GOOGLE_CREDS as a file path.")
    else:
        # If GOOGLE_CREDS is not set, default to 'credentials.json' file
        creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPES)
        logger.info("Google Sheets API initialized successfully using 'credentials.json' file.")

    sheets_service = build('sheets', 'v4', credentials=creds)

except Exception as e:
    logger.error(f"Google Sheets API setup failed: {e}", exc_info=True)
    # Re-raise the exception to stop the application if a critical service fails
    raise

# Gemini 2.0 Flash setup
try:
    # Configure Gemini API with the API key from environment variables
    genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
    gemini_model = genai.GenerativeModel('gemini-2.0-flash')
    logger.info("Gemini API initialized successfully.")
except Exception as e:
    logger.error(f"Gemini API setup failed: {e}", exc_info=True)
    # Re-raise the exception to stop the application if a critical service fails
    raise

def get_db_connection():
    """Establishes and returns a new PostgreSQL database connection."""
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        logger.info("Database connection established.")
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}", exc_info=True)
        raise # Propagate the exception to the caller

# Existing upload route (preserved and modified for StockBook schema)
@app.route('/upload', methods=['POST', 'OPTIONS'])
def upload_files():
    """
    Handles file uploads, processes them (placeholder for Gemini logic),
    inserts data into the StockBook table, and syncs to Google Sheets.
    """
    if request.method == 'OPTIONS':
        # Handle CORS preflight request
        return '', 200
    try:
        if 'files' not in request.files:
            logger.warning("No files in request")
            return jsonify({'error': 'No files uploaded'}), 400
        files = request.files.getlist('files')
        if not files or all(f.filename == '' for f in files):
            logger.warning("Empty file list or no valid files")
            return jsonify({'error': 'No valid files uploaded'}), 400

        data_entries = []
        for file_item in files: # Renamed 'file' to 'file_item' to avoid conflict with `file` (builtin)
            # Placeholder for Gemini logic. In a real scenario, this would extract data from the file.
            gemini_result = {}  # Replace with your original Gemini logic
            entry = {
                'Date': datetime.now().strftime('%Y-%m-%d'),
                'Particulars': gemini_result.get('description', 'Processed File'),
                'VoucherBillNo': gemini_result.get('bill_no', 'N/A'),
                'ReceiptQuantity': gemini_result.get('quantity', 0),
                'ReceiptAmount': float(gemini_result.get('amount', 0.0)),
                'IssuedQuantity': 0,
                'IssuedAmount': 0.0,
                'BalanceQuantity': gemini_result.get('quantity', 0),
                'BalanceAmount': float(gemini_result.get('amount', 0.0))
            }
            data_entries.append(entry)

        logger.debug(f"Data entries prepared for DB insertion in /upload: {json.dumps(data_entries, indent=2)}")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor) # Use RealDictCursor for dictionary-like rows

        # Insert data into StockBook table
        for entry in data_entries:
            sql_query = """
                INSERT INTO StockBook (Date, Particulars, VoucherBillNo, ReceiptQuantity, ReceiptAmount,
                                     IssuedQuantity, IssuedAmount, BalanceQuantity, BalanceAmount)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING TransactionID; -- Return the auto-generated TransactionID
            """
            params = (
                entry['Date'], entry['Particulars'], entry['VoucherBillNo'],
                entry['ReceiptQuantity'], entry['ReceiptAmount'],
                entry['IssuedQuantity'], entry['IssuedAmount'],
                entry['BalanceQuantity'], entry['BalanceAmount']
            )
            logger.debug(f"Executing SQL in /upload: {sql_query} with params: {params}")
            
            try:
                cur.execute(sql_query, params)
                # Fetch the returned TransactionID and add it to the entry dictionary
                returned_id = cur.fetchone()
                if returned_id:
                    entry['TransactionID'] = returned_id['transactionid'] # Column names returned by psycopg2 are lowercase
                    logger.debug(f"Successfully inserted row, TransactionID: {entry['TransactionID']}")
                else:
                    logger.warning("No TransactionID returned after INSERT. Row might not have been inserted.")
            except psycopg2.Error as db_error:
                logger.error(f"Database error during insert in /upload: {db_error}", exc_info=True)
                raise # Re-raise to trigger rollback and general error handling
            
        conn.commit() # Commit the transaction to save changes to the database
        logger.info("Database commit successful in /upload.")

        # Sync data to Google Sheets
        spreadsheet_id = os.getenv('SPREADSHEET_ID', 'your_spreadsheet_id')
        values = [[e['TransactionID'], e['Date'], e['Particulars'], e['VoucherBillNo'],
                   e['ReceiptQuantity'], e['ReceiptAmount'], e['IssuedQuantity'],
                   e['IssuedAmount'], e['BalanceQuantity'], e['BalanceAmount']]
                  for e in data_entries]
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range='A1', # Append to the first sheet, starting at A1
            valueInputOption='RAW', # Interpret input data as raw values
            body={'values': values}
        ).execute()
        logger.info("Data synced to Google Sheets in /upload.")

        cur.close()
        conn.close()
        logger.info(f"Uploaded {len(files)} files successfully via /upload and synced to Google Sheets.")
        return jsonify({'message': 'Files processed and synced'}), 200

    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True) # Log full traceback
        # Rollback in case of error
        if 'conn' in locals() and conn:
            conn.rollback()
            logger.warning("Database transaction rolled back in /upload due to error.")
        return jsonify({'error': str(e)}), 500

# Updated upload-flash route with detailed error logging and StockBook schema alignment
@app.route('/upload-flash', methods=['POST', 'OPTIONS'])
def upload_files_flash():
    """
    Handles file uploads, processes them with Gemini 2.0 Flash,
    inserts data into the StockBook table, and syncs to Google Sheets.
    """
    if request.method == 'OPTIONS':
        # Handle CORS preflight request
        return '', 200
    try:
        if 'files' not in request.files:
            logger.warning("No files in request in /upload-flash")
            return jsonify({'error': 'No files uploaded'}), 400
        files = request.files.getlist('files')
        if not files or all(f.filename == '' for f in files):
            logger.warning("Empty file list or no valid files in /upload-flash")
            return jsonify({'error': 'No valid files uploaded'}), 400

        logger.info(f"Processing {len(files)} files with Gemini 2.0 Flash in /upload-flash")
        data_entries = []
        for file_item in files:
            try:
                # Read file content and prepare for Gemini API
                file_content = file_item.read()
                logger.debug(f"Processing file: {file_item.filename}, size: {len(file_content)} bytes, mimetype: {file_item.mimetype}")

                # Call Gemini API to extract data
                response = gemini_model.generate_content([
                    {"mime_type": file_item.mimetype, "data": file_content},
                    {"text": "Extract financial data: description, bill number, quantity, amount. Respond as a JSON object with keys 'description', 'bill_no', 'quantity', 'amount'."}
                ])
                gemini_result_text = response.text
                logger.debug(f"Gemini raw result: {gemini_result_text}")

                # Parse Gemini's JSON response
                try:
                    gemini_data = json.loads(gemini_result_text)
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse Gemini JSON: {gemini_result_text}. Setting fallback data.", exc_info=True)
                    # Fallback if Gemini doesn't return perfect JSON
                    gemini_data = {
                        'description': gemini_result_text, # Use the raw text as description
                        'bill_no': 'N/A',
                        'quantity': 0,
                        'amount': 0.0
                    }

                # Map Gemini data to StockBook schema
                entry = {
                    'Date': datetime.now().strftime('%Y-%m-%d'),
                    'Particulars': gemini_data.get('description', 'Processed File'),
                    'VoucherBillNo': gemini_data.get('bill_no', 'N/A'),
                    'ReceiptQuantity': float(gemini_data.get('quantity', 0)), # Ensure float for DECIMAL type
                    'ReceiptAmount': float(gemini_data.get('amount', 0.0)),
                    'IssuedQuantity': 0.0, # Default to 0.0 for quantities, 0.0 for amounts
                    'IssuedAmount': 0.0,
                    'BalanceQuantity': float(gemini_data.get('quantity', 0)),
                    'BalanceAmount': float(gemini_data.get('amount', 0.0))
                }
                data_entries.append(entry)
            except Exception as e:
                logger.error(f"Gemini processing failed for {file_item.filename}: {e}", exc_info=True)
                # Decide whether to raise or continue; here, re-raise to fail the whole request
                raise

        logger.debug(f"Data entries prepared for DB insertion in /upload-flash: {json.dumps(data_entries, indent=2)}")
        logger.info("Inserting into PostgreSQL StockBook table.")
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        for entry in data_entries:
            sql_query = """
                INSERT INTO StockBook (Date, Particulars, VoucherBillNo, ReceiptQuantity, ReceiptAmount,
                                     IssuedQuantity, IssuedAmount, BalanceQuantity, BalanceAmount)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING TransactionID;
            """
            params = (
                entry['Date'], entry['Particulars'], entry['VoucherBillNo'],
                entry['ReceiptQuantity'], entry['ReceiptAmount'],
                entry['IssuedQuantity'], entry['IssuedAmount'],
                entry['BalanceQuantity'], entry['BalanceAmount']
            )
            logger.debug(f"Executing SQL in /upload-flash: {sql_query} with params: {params}")

            try:
                cur.execute(sql_query, params)
                returned_id = cur.fetchone()
                if returned_id:
                    entry['TransactionID'] = returned_id['transactionid'] # psycopg2 returns column names in lowercase
                    logger.debug(f"Successfully inserted row, TransactionID: {entry['TransactionID']}")
                else:
                    logger.warning("No TransactionID returned after INSERT in /upload-flash. Row might not have been inserted.")
            except psycopg2.Error as db_error:
                logger.error(f"Database error during insert in /upload-flash: {db_error}", exc_info=True)
                raise # Re-raise to trigger rollback and general error handling
            
        conn.commit()
        logger.info("Database commit successful in /upload-flash.")

        logger.info("Syncing to Google Sheets.")
        spreadsheet_id = os.getenv('SPREADSHEET_ID', 'your_spreadsheet_id')
        values = [[e['TransactionID'], e['Date'], e['Particulars'], e['VoucherBillNo'],
                   e['ReceiptQuantity'], e['ReceiptAmount'], e['IssuedQuantity'],
                   e['IssuedAmount'], e['BalanceQuantity'], e['BalanceAmount']]
                  for e in data_entries]

        # Append data to the Google Sheet
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range='A1',
            valueInputOption='RAW',
            body={'values': values}
        ).execute()
        logger.info("Data synced to Google Sheets in /upload-flash.")

        cur.close()
        conn.close()
        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit" # Link for editing the sheet
        logger.info(f"Upload successful, sheet URL: {sheet_url}")
        return jsonify({'message': 'Files processed and synced to Google Sheet', 'sheet_url': sheet_url}), 200

    except Exception as e:
        logger.error(f"Upload-flash error: {e}", exc_info=True)
        if 'conn' in locals() and conn:
            conn.rollback() # Ensure rollback on error
            logger.warning("Database transaction rolled back in /upload-flash due to error.")
        return jsonify({'error': f"Failed to process files: {str(e)}"}), 500

@app.route('/results', methods=['GET'])
def get_results():
    """Retrieves all data from the StockBook table."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Select all columns from StockBook, ordered by TransactionID
        cur.execute("SELECT * FROM StockBook ORDER BY TransactionID")
        data = cur.fetchall()
        cur.close()
        conn.close()
        logger.info("Fetched results successfully from StockBook table.")
        return jsonify(data), 200
    except Exception as e:
        logger.error(f"Results error: {e}", exc_info=True)
        return jsonify({'error': 'Failed to load data from StockBook'}), 500

@app.route('/update', methods=['POST'])
def update_data():
    """Updates existing data in the StockBook table and syncs to Google Sheets."""
    try:
        updates = request.json # Expects a list of dictionaries, each representing a row to update
        logger.debug(f"Received updates for DB in /update: {json.dumps(updates, indent=2)}")

        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        for update in updates:
            sql_query = """
                UPDATE StockBook
                SET Date = %s, Particulars = %s, VoucherBillNo = %s,
                    ReceiptQuantity = %s, ReceiptAmount = %s,
                    IssuedQuantity = %s, IssuedAmount = %s,
                    BalanceQuantity = %s, BalanceAmount = %s
                WHERE TransactionID = %s
            """
            params = (
                update['Date'], update['Particulars'], update['VoucherBillNo'],
                update['ReceiptQuantity'], update['ReceiptAmount'],
                update['IssuedQuantity'], update['IssuedAmount'],
                update['BalanceQuantity'], update['BalanceAmount'],
                update['TransactionID'] # Use TransactionID for WHERE clause
            )
            logger.debug(f"Executing SQL in /update: {sql_query} with params: {params}")
            
            try:
                cur.execute(sql_query, params)
                if cur.rowcount == 0:
                    logger.warning(f"No row updated for TransactionID: {update['TransactionID']}")
            except psycopg2.Error as db_error:
                logger.error(f"Database error during update in /update: {db_error}", exc_info=True)
                raise # Re-raise to trigger rollback and general error handling

        conn.commit()
        logger.info("Database commit successful in /update.")

        # Sync all data back to Google Sheets (clear and rewrite for simplicity in update)
        spreadsheet_id = os.getenv('SPREADSHEET_ID', 'your_spreadsheet_id')
        
        # Fetch all data after update for full sync to sheets
        cur.execute("SELECT * FROM StockBook ORDER BY TransactionID")
        all_data_after_update = cur.fetchall()
        logger.debug(f"All data fetched for Google Sheet sync: {json.dumps(all_data_after_update, indent=2)}")

        # Prepare values for Google Sheets, ensuring headers are included for clarity
        headers = ['TransactionID', 'Date', 'Particulars', 'VoucherBillNo', 'ReceiptQuantity',
                   'ReceiptAmount', 'IssuedQuantity', 'IssuedAmount', 'BalanceQuantity', 'BalanceAmount']
        
        values_to_write = [headers] + [[d['transactionid'], d['date'].strftime('%Y-%m-%d'), d['particulars'], d['voucherbillno'],
                                         d['receiptquantity'], d['receiptamount'], d['issuedquantity'],
                                         d['issuedamount'], d['balancequantity'], d['balanceamount']]
                                        for d in all_data_after_update]

        # Clear existing data in the sheet before updating
        sheets_service.spreadsheets().values().clear(spreadsheetId=spreadsheet_id, range='A1:J').execute()
        # Update the sheet with the latest data
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range='A1', valueInputOption='RAW', body={'values': values_to_write}
        ).execute()
        logger.info("Data synced to Google Sheets in /update.")

        cur.close()
        conn.close()
        logger.info("Data updated successfully in StockBook and synced to Google Sheets.")
        return jsonify({'message': 'Data updated'}), 200
    except Exception as e:
        logger.error(f"Update error: {e}", exc_info=True)
        if 'conn' in locals() and conn:
            conn.rollback()
            logger.warning("Database transaction rolled back in /update due to error.")
        return jsonify({'error': str(e)}), 500

@app.route('/export-to-sheet', methods=['POST'])
def export_to_sheet():
    """
    Exports provided data to a new Google Sheet.
    This route expects the full dataset to be sent in the request body.
    """
    try:
        data = request.json # Expects a list of dictionaries representing the data to export
        logger.debug(f"Received data for export in /export-to-sheet: {json.dumps(data, indent=2)}")

        # Create a new spreadsheet with a dynamic title
        spreadsheet = sheets_service.spreadsheets().create(
            body={'properties': {'title': f'Exported_StockBook_Results_{datetime.now().strftime("%Y%m%d_%H%M%S")}'}}
        ).execute()
        spreadsheet_id = spreadsheet['spreadsheetId']
        
        # Define headers according to StockBook schema
        headers = ['TransactionID', 'Date', 'Particulars', 'VoucherBillNo', 'ReceiptQuantity',
                   'ReceiptAmount', 'IssuedQuantity', 'IssuedAmount', 'BalanceQuantity', 'BalanceAmount']
        
        # Prepare values for the new sheet, including headers
        values = [headers] + [[d['TransactionID'], d['Date'], d['Particulars'], d['VoucherBillNo'],
                               d['ReceiptQuantity'], d['ReceiptAmount'], d['IssuedQuantity'],
                               d['IssuedAmount'], d['BalanceQuantity'], d['BalanceAmount']]
                              for d in data]
        
        # Update the new sheet with the prepared values
        sheets_service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range='A1', valueInputOption='RAW', body={'values': values}
        ).execute()

        shareable_link = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        logger.info(f"Data exported to new sheet: {shareable_link}")
        return jsonify({'message': 'Sheet created', 'link': shareable_link}), 200
    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Get port from environment variable, default to 5000
    port = int(os.environ.get("PORT", 5000))
    # Run the Flask app
    app.run(host='0.0.0.0', port=port, debug=True)
