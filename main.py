import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()

# CORS Middleware config (Keeps your Vercel connection working)
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

# Schema for incoming job submissions from the frontend form
class JobSubmission(BaseModel):
    full_name: str
    phone_number: str
    problem_category: str
    description: str
    # Add any extra form fields if Olamiposi is sending them (e.g. zone_number, street_number, building_number)

# Schema for WhatsApp verification string tasks
class WhatsAppAlert(BaseModel):
    message: str
    recipient: str

@app.get("/")
def read_root():
    return {"message": "FastAPI backend is live and running perfectly on Render!"}

# --- ADD THIS NEW ROUTE TO FIX THE 404 ERROR ---
@app.post("/jobs")
async def create_job(job: JobSubmission):
    try:
        # Prepare data structure for your Supabase table
        data = {
            "full_name": job.full_name,
            "phone_number": job.phone_number,
            "problem_category": job.problem_category,
            "description": job.description
        }
        
        # Insert data into your Supabase 'jobs' table
        response = supabase.table("jobs").insert(data).execute()
        
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
    print(f"Sending Alert: {alert.message}")
    print(f"To: {alert.recipient}")
    print("------------------------------------")
    return {
        "status": "success",
        "message": "WhatsApp dispatch alert processed successfully",
        "dispatched_string": alert.message
    }