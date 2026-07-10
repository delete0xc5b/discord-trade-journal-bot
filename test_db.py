import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
# Print this to be 100% sure your script is actually reading the .env file correctly
db_url = os.getenv('DATABASE_URL')
print(f"Connecting to: {db_url.split('@')[1]}") # Prints the host, masks the password

try:
    conn = psycopg2.connect(db_url)
    print("SUCCESS: Connection successful!")
    conn.close()
except Exception as e:
    print(f"FAILED: {e}")