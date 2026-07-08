from firebase_admin import firestore
import firebase_services

firebase_services.initialize_firebase()

db = firestore.client()

collections = list(db.collections())

print("Connected!")
print(collections)