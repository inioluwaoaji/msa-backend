import os
from fastapi import FastAPI
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

app = FastAPI()

# Supabase configuration setup
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# Schema for WhatsApp verification string tasks
class WhatsAppAlert(BaseModel):
    message: str
    recipient: str

@app.get("/")
def read_root():
    return {"message": "FastAPI backend is live and running perfectly on Render!"}

@app.post("/webhook/whatsapp")
async def whatsapp_dispatch_webhook(alert: WhatsAppAlert):
    # This verifies the production live webhook handles outgoing alert strings
    print("--- WhatsApp Dispatch Triggered ---")
    print(f"Sending Alert: {alert.message}")
    print(f"To: {alert.recipient}")
    print("------------------------------------")
    return {
        "status": "success",
        "message": "WhatsApp dispatch alert processed successfully",
        "dispatched_string": alert.message
    }