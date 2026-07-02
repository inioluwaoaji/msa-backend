import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from supabase import create_client, Client

app = FastAPI(title="Maynd Stomir Backend API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

class FreelanceApplication(BaseModel):
    full_name: str
    email: str
    phone_number: str
    trade: str  
    experience_years: int
    kahramaa_id_url: str  
    notes: Optional[str] = None

@app.get("/")
def read_root():
    return {"status": "healthy", "message": "Maynd Stomir Backend API is running"}

@app.post("/freelance_applications")
async def create_application(application: FreelanceApplication):
    try:
        data = {
            "full_name": application.full_name,
            "email": application.email,
            "phone_number": application.phone_number,
            "position": application.trade,  
            "experience_years": application.experience_years,
            "kahramaa_id_url": application.kahramaa_id_url,
            "notes": application.notes
        }
        
        # Fixed: Changed back to plural 'freelance_applications' to match Supabase database path
        response = supabase.table("freelance_applications").insert(data).execute()
        return {"success": True, "data": response.data}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))