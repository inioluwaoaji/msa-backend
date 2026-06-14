import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()

# --- ADD CORS MIDDLEWARE HERE TO FIX THE VERCEL ERROR ---
# This allows your live frontend on Vercel to communicate with this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://maynd-stomir.vercel.app",  # Olamiposi's live frontend
        "http://localhost:3000",             # Local development if needed
    ],
    allow_credentials=True,
    allow_methods=["*"],  # Allows all HTTP methods (POST, GET, etc.)
    allow_headers=["*"],  # Allows all headers
)

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
    print("--- WhatsApp Dispatch Triggered ---")
    print(f"Sending Alert: {alert.message}")
    print(f"To: {alert.recipient}")
    print("------------------------------------")
    return {
        "status": "success",
        "message": "WhatsApp dispatch alert processed successfully",
        "dispatched_string": alert.message
    }