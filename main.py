import os
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()

# CORS Middleware config
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://maynd-stomir.vercel.app",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase configuration setup
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# --- UPDATED DATA SCHEMA (Optional catch-all to prevent 422 errors) ---
class JobSubmission(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    problem_category: Optional[str] = None
    description: Optional[str] = None
    zone_number: Optional[str] = None
    street_number: Optional[str] = None
    building_number: Optional[str] = None
    preferred_date: Optional[str] = None
    preferred_time: Optional[str] = None

class WhatsAppAlert(BaseModel):
    message: str
    recipient: str

@app.get("/")
def read_root():
    return {"message": "FastAPI backend is live and running perfectly on Render!"}

@app.post("/jobs")
async def create_job(job: JobSubmission):
    try:
        # Capture all possible incoming fields from the form submission
        data = {
            "full_name": job.full_name,
            "phone_number": job.phone_number,
            "problem_category": job.problem_category,
            "description": job.description,
            "zone_number": job.zone_number,
            "street_number": job.street_number,
            "building_number": job.building_number,
            "preferred_date": job.preferred_date,
            "preferred_time": job.preferred_time
        }
        
        # Strip out any keys that are None so we don't accidentally override database defaults
        cleaned_data = {k: v for k, v in data.items() if v is not None}
        
        # Insert data directly into your Supabase 'jobs' table
        response = supabase.table("jobs").insert(cleaned_data).execute()
        
        return {
            "status": "success", 
            "message": "Job logged successfully!", 
            "data": response.data
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/webhook/whatsapp")
async def whatsapp_dispatch_webhook(alert: WhatsAppAlert):
    print("--- WhatsApp Dispatch Triggered ---")
    return {
        "status": "success",
        "message": "WhatsApp dispatch alert processed successfully"
    }