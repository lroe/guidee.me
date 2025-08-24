import os
import random
from app import app, db, User
from sqlalchemy import or_

def assign_random_avatars():
    """
    Finds all users with the default avatar and assigns them a random
    avatar from the 'main_set' folder.
    """
    # This 'with' block is essential to connect the script to your app's database
    with app.app_context():
        print("Starting avatar assignment process...")

        # --- 1. Get the list of available new avatars ---
        avatar_path = os.path.join(app.static_folder, 'images/main_set')
        if not os.path.exists(avatar_path):
            print(f"Error: The avatar folder '{avatar_path}' does not exist. Please create it and add your avatars.")
            return

        avatars = [f'/static/images/main_set/{f}' for f in os.listdir(avatar_path) if f.endswith(('.png', '.jpg', '.jpeg', '.gif'))]

        if not avatars:
            print("Error: No avatars found in the 'main_set' folder.")
            return

        print(f"Found {len(avatars)} new avatars to assign.")

        # --- 2. Find all users who need a new avatar ---
        # This targets users with the specific default URL or a null value, just in case.
        default_avatar_url = '/static/images/avatars/default.png'
        users_to_update = User.query.filter(
            or_(User.avatar_url == default_avatar_url, User.avatar_url.is_(None))
        ).all()

        if not users_to_update:
            print("No users found with the default avatar. Nothing to do.")
            return

        print(f"Found {len(users_to_update)} users to update.")

        # --- 3. Loop through the users and assign a random avatar ---
        for user in users_to_update:
            new_avatar = random.choice(avatars)
            user.avatar_url = new_avatar
            print(f"  - Assigning '{new_avatar}' to user: {user.username}")

        # --- 4. Commit all the changes to the database at once ---
        try:
            db.session.commit()
            print("\nSuccessfully updated all users in the database!")
        except Exception as e:
            db.session.rollback()
            print(f"\nAn error occurred. Rolling back changes. Error: {e}")

# This makes the script runnable from the command line
if __name__ == '__main__':
    assign_random_avatars()
