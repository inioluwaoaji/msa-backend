import os
import httpx
from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List
from supabase import create_client, Client

# Initialize FastAPI App
app = FastAPI(
    title="Maynd Stomir Backend API",
    description="Production backend pipeline handling jobs, tracking, and automated dispatch logic.",
    version="1.1.0"
)

# 1. CORS Configuration Security Layer
# Resolves the origin blockages between Vercel and Render
ORIGINS = [
    "https://maynd-stomir.vercel.app",
    "http://localhost:3000",
    "http://127.0.0.1:5500"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Supabase Production Connection Client
# Initialized cleanly without strict schema overrides to resolve PGRST125 foreign table bugs
SUPABASE_URL: str = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY: str = os.environ.get("SUPABASE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("⚠️ WARNING: Missing Supabase Environment Variables!")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# 3. Pydantic Models for Validation
# Includes backend validation constraints for the Qatari operational rule matrix
class JobSubmission(BaseModel):
    full_name: str = Field(..., description="Must match the names on uploaded QID.")
    phone_number: str = Field(..., min_length=8, max_length=8, description="Must be restricted to exactly 8 digits.")
    description: str
    category: str
    preferred_date: str
    preferred_time: str
    id_photo_url: Optional[str] = None
    job_photo_url: Optional[str] = None


# 4. Helper Function for Automated Outbound Notification
async def send_whatsapp_message(to_number: str, message: str):
    """
    Background worker that forwards the notification payload to the external WhatsApp gateway provider.
    """
    gateway_url = "https://api.whatsapp.com/v1/messages" 
    whatsapp_api_key = os.environ.get("WHATSAPP_API_KEY", "")
    
    if not whatsapp_api_key:
        print("❌ Error: WHATSAPP_API_KEY environment variable is not set.")
        return

    headers = {
        "Authorization": f"Bearer {whatsapp_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message}
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(gateway_url, json=payload, headers=headers)
            response.raise_for_status()
            print(f"✅ WhatsApp alert successfully sent to {to_number}")
        except httpx.HTTPError as e:
            print(f"❌ WhatsApp Gateway Communication Error: {e}")


# 5. Core API Routes
@app.post("/jobs", status_code=201)
async def create_job(job: JobSubmission, background_tasks: BackgroundTasks):
    """
    Receives frontend maintenance request payloads, pushes them straight into the Supabase 'jobs' table,
    and handles background triggers for automated WhatsApp dispatching.
    """
    try:
        # Convert Pydantic object to dictionary for database insertion
        job_data = job.model_dump()
        
        # Execute Supabase insert targeting the foreign relation schema mapping natively
        db_query = supabase.table("jobs").insert(job_data).execute()
        
        # Extract record list from the database response object
        inserted_records = getattr(db_query, "data", [])
        
        if not inserted_records:
            raise HTTPException(
                status_code=500, 
                detail="Database sync pending. Record failed to create or write cleanly inside database."
            )
        
        new_job = inserted_records[0]
        job_id = new_job.get("id")
        
        # Build the exclusive tracking link requested by Yemi
        tracking_url = f"https://maynd-stomir.vercel.app/status.html?id={job_id}"
        
        # Queue the Tuesday Automated WhatsApp task so it triggers immediately upon success
        notification_msg = (
            f"🛠️ *Maynd Stomir - Request Confirmed*\n\n"
            f"Hi {job.full_name},\n"
            f"Your maintenance request has been submitted successfully.\n\n"
            f"📦 *Job ID:* {job_id}\n"
            f"📋 *Category:* {job.category}\n\n"
            f"🔗 *Track Your Job Progress Live Here:* {tracking_url}"
        )
        background_tasks.add_task(send_whatsapp_message, job.phone_number, notification_msg)
        
        # Return pristine JSON structure back to Olamiposi's frontend script
        return {
            "status": "success",
            "message": "Job logged successfully into Supabase!",
            "data": inserted_records
        }

    except Exception as error:
        print(f"Backend Crash Logged: {str(error)}")
        raise HTTPException(status_code=500, detail=f"Internal Database Link Failure: {str(error)}")


@app.post("/webhook/whatsapp")
async def whatsapp_status_webhook(payload: dict, background_tasks: BackgroundTasks):
    """
    Dedicated operational endpoint to handle status shifts (e.g. tracking updates from the dashboard).
    """
    record = payload.get("record", {})
    job_id = record.get("id")
    current_status = record.get("status", "PENDING")
    phone_number = record.get("phone_number")
    customer_name = record.get("full_name", "Customer")
    
    if not job_id or not phone_number:
        raise HTTPException(status_code=400, detail="Missing critical job tracking parameters.")
        
    tracking_url = f"https://maynd-stomir.vercel.app/status.html?id={job_id}"
    
    update_msg = (
        f"🛠️ *Maynd Stomir Status Update*\n\n"
        f"Hello {customer_name},\n"
        f"The status of your maintenance request (Job ID: {job_id}) has changed to: *{current_status}*.\n\n"
        f"👉 *Monitor live technician updates here:* {tracking_url}"
    )
    
    background_tasks.add_task(send_whatsapp_message, phone_number, update_msg)
    return {"status": "success", "message": "WhatsApp tracking status dispatch processed."}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "environment": "production"}