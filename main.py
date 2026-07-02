import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional
from supabase import create_client, Client

app = FastAPI(title="Maynd Stomir Backend API")

# Configure CORS so Olamiposi's frontend can communicate with the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this to specific domains in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase Client using environment variables
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Define the data schema matching the frontend payload structure
class FreelanceApplication(BaseModel):
    fullName: str
    email: EmailStr
    phoneNumber: str
    position: str
    experienceYears: int
    kahramaaIdUrl: str  # Dynamically accepts the Supabase storage bucket URL string
    notes: Optional[str] = None

@app.get("/")
def read_root():
    return {"status": "healthy", "message": "Maynd Stomir Backend API is running"}

@app.post("/freelance_applications")
async def create_application(application: FreelanceApplication):
    try:
        # Map the incoming camelCase payload to your database schema format
        data = {
            "full_name": application.fullName,
            "email": application.email,
            "phone_number": application.phoneNumber,
            "position": application.position,
            "experience_years": application.experienceYears,
            "kahramaa_id_url": application.kahramaaIdUrl,
            "notes": application.notes
        }
        
        # Fixed: Using the singular table name 'freelance_application' to prevent PGRST125 errors
        response = supabase.table("freelance_application").insert(data).execute()
        
        return {"success": True, "data": response.data}
        
    except Exception as e:
        # Wrap any database execution errors inside an Internal Server Error response
        raise HTTPException(status_code=500, detail=str(e))