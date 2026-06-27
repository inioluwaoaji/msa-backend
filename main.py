import os
import math
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI(title="MindStormerX Production Network")

# Universal CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global error shield to prevent silent CORS drops
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": f"Server Exception: {str(exc)}"},
        headers={"Access-Control-Allow-Origin": "*"}
    )

# Safely connect to Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
except Exception:
    supabase = None

class JobSubmission(BaseModel):
    full_name: str
    email: str
    phone_number: str  
    category: str
    description: str
    preferred_date: str
    preferred_time: str
    client_lat: float  
    client_lng: float  

class TechnicianApplication(BaseModel):
    full_name: str
    phone_number: str
    email: str
    trade: str
    experience_years: int  
    qid_number: str
    kahramaa_id: str       
    id_photo_url: str

@app.get("/")
async def root_health_check():
    return {"status": "healthy"}

@app.post("/jobs")
async def create_job(job: JobSubmission):
    return {"status": "success", "message": "Job received"}

@app.post("/freelance_applications")
async def register_technician(tech: TechnicianApplication):
    if not supabase:
        return JSONResponse(status_code=500, content={"error": "Database credentials uninitialized."})

    insert_data = {
        "full_name": tech.full_name,
        "phone_number": tech.phone_number,
        "email": tech.email,
        "trade": tech.trade.lower(),
        "experience_years": tech.experience_years,
        "qid_number": tech.qid_number,
        "kahramaa_id": tech.kahramaa_id,
        "id_photo_url": tech.id_photo_url,
        "latitude": 25.2854,  
        "longitude": 51.5310
    }

    # Explicitly try the name found in your dashboard first, then fall back
    for table_name in ["freelance_applications", "technicians", "technician"]:
        try:
            supabase.table(table_name).insert(insert_data).execute()
            return {
                "status": "success",
                "message": "Application saved successfully!",
                "popup_data": {"technician_notice": "Registration complete!"}
            }
        except Exception as e:
            last_err = str(e)
            if "PGRST125" not in last_err:
                return JSONResponse(status_code=500, content={"error": f"Database schema reject: {last_err}"})
            continue

    return JSONResponse(status_code=500, content={"error": f"Could not find valid table target: {last_err}"})