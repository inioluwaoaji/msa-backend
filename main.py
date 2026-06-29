import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client

app = Flask(__name__)
# Enable CORS for frontend handshakes
CORS(app, resources={r"/*": {"origins": "*"}})

# Initialize Supabase Client
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/freelance_applications', methods=['POST', 'OPTIONS'])
def handle_freelance_application():
    # Handle preflight CORS requests cleanly
    if request.method == 'OPTIONS':
        return '', 200

    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # CRUCIAL FIX: Targeted 'freelance_applications' (plural) to match your database schema
        response = supabase.table('freelance_applications').insert({
            "full_name": data.get("full_name"),
            "email": data.get("email"),
            "phone_number": data.get("phone_number"),
            "qid_number": data.get("qid_number"),
            "years_of_experience": data.get("years_of_experience"),
            "trade": data.get("trade"),
            "kahramaa_id_url": data.get("kahramaa_id_url"),  # URL from Olamiposi's upload step
            "profile_photo_url": data.get("profile_photo_url")
        }).execute()

        # Trigger your automated dispatch / background pipelines here if needed

        return jsonify({
            "status": "success", 
            "message": "Application saved successfully!",
            "data": response.data
        }), 201

    except Exception as e:
        print(f"Backend Crash Log: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Internal Server Error occurred during insertion.",
            "details": str(e)
        }), 500

if __name__ == '__main__':
    # Default port for Render deployments
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)