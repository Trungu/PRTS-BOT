# import os
# from dotenv import load_dotenv
# from supabase import create_client, Client
# from datetime import datetime, timezone

# load_dotenv()

# url: str = os.environ.get("SUPABASE_URL")
# key: str = os.environ.get("SUPABASE_KEY")

# supabase: Client = create_client(url, key)

# print("SUPABASE_URL:", url)
# print("SUPABASE_KEY prefix:", key[:8] if key else None)

# response = supabase.table("profiles").select("*").limit(1).execute()

# try:
#     response = supabase.table("profiles").select("*").limit(1).execute()
#     print("✅ Connected. Data:", response.data)
# except Exception as e:
#     print("❌ Supabase error:", e)

# # Example: insert a test record (uncomment to run)
# from datetime import datetime

# try:
#     # INSERT
#     insert_res = supabase.table("profiles").insert({
#         "id": 493435684,
#         "created_at": datetime.now(timezone.utc).isoformat()
#     }).execute()

#     print("✅ Inserted:", insert_res.data)

#     # READ BACK
#     select_res = (
#         supabase.table("profiles")
#         .select("*")
#         .order("created_at", desc=True)
#         .limit(5)
#         .execute()
#     )

#     print("📦 Latest rows:", select_res.data)

# except Exception as e:
#     print("❌ Error:", e)