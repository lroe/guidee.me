import os
from app import app, db, User
from sqlalchemy import func

def find_and_fix_duplicate_usernames():
    with app.app_context():
        # Find usernames with counts greater than 1
        duplicates = db.session.query(User.username, func.count(User.username)).group_by(User.username).having(func.count(User.username) > 1).all()

        if not duplicates:
            print("No duplicate usernames found.")
            return

        print(f"Found {len(duplicates)} duplicate username(s).")

        for username, count in duplicates:
            print(f"Fixing username: {username}")
            # Get all users with the duplicate username
            users_with_duplicate = User.query.filter_by(username=username).all()
            
            for i, user in enumerate(users_with_duplicate):
                # Keep the first user's username as is
                if i == 0:
                    continue
                
                # Append a number to make the username unique
                new_username = f"{user.username}_{i+1}"
                
                # Check if the new username already exists
                while User.query.filter_by(username=new_username).first() is not None:
                    i += 1
                    new_username = f"{user.username}_{i+1}"

                print(f"  Updating user {user.id} to {new_username}")
                user.username = new_username
        
        db.session.commit()
        print("Finished fixing duplicate usernames.")

if __name__ == '__main__':
    find_and_fix_duplicate_usernames()
