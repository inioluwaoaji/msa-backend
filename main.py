import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client

app = FastAPI()

# Enable CORS matching your original configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Supabase Client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.post("/freelance_applications")
async def handle_freelance_application(request: Request):
    try:
        data = await request.json()
        if not data:
            raise HTTPException(status_code=400, detail="No data provided")

        # TARGETS THE PLURAL TABLE NAME TO FIX PGRST125
        response = supabase.table('freelance_applications').insert({
            "full_name": data.get("full_name"),
            "email": data.get("email"),
            "phone_number": data.get("phone_number"),
            "qid_number": data.get("qid_number"),
            "years_of_experience": data.get("years_of_experience"),
            "trade": data.get("trade"),
            "kahramaa_id_url": data.get("kahramaa_id_url"),
            "profile_photo_url": data.get("profile_photo_url")
        }).execute()

        return {
            "status": "success", 
            "message": "Application saved successfully!",
            "data": response.data
        }

    except Exception as e:
        print(f"Backend Crash Log: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))