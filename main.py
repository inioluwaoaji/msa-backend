import os
import resend
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# Initialize Resend with your API key
resend.api_key = os.environ.get("RESEND_API_KEY")

# ... (Keep your JobSubmission Pydantic model here)

@app.post("/jobs", status_code=201)
async def create_job(job: JobSubmission):
    # 1. Your existing logic to save the job to Supabase goes here
    
    # 2. Build the Email Content
    email_html_content = f"""
    <h3>🛠️ New Job Request Submitted</h3>
    <p><strong>Client Name:</strong> {job.full_name}</p>
    <p><strong>Email:</strong> {job.email}</p>
    <p><strong>Phone:</strong> {job.phone_number}</p>
    <p><strong>Category:</strong> {job.category}</p>
    <p><strong>Description:</strong> {job.description}</p>
    <p><strong>Preferred Slot:</strong> {job.preferred_date} at {job.preferred_time}</p>
    """
    
    try:
        # Send Alert to Technicians / Olamiposi
        resend.Emails.send({{
            "from": "Maynd Stomir Alerts <onboarding@resend.dev>",
            "to": ["olamiposi@yourdomain.com", "your-email@domain.com"], # Add your technician team emails here
            "subject": f"🚨 New Job Assigned: {job.category.upper()}",
            "html": email_html_content
        }})
        
        # Send Confirmation Receipt to the Client
        resend.Emails.send({{
            "from": "Maynd Stomir <onboarding@resend.dev>",
            "to": [job.email], # Sends directly to the client's email address
            "subject": "🛠️ Your Service Request is Confirmed!",
            "html": f"<h3>Hi {job.full_name},</h3><p>We have received your request for {job.category}. A technician will review it shortly!</p>"
        }})
        
    except Exception as e:
        # Don't let an email failure crash the database save action
        print(f"Email dispatch error: {str(e)}")
        
    return {"status": "success", "message": "Job created and emails dispatched."}