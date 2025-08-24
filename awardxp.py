
import argparse
import datetime
from app import app, db, User, award_xp

def run_award_xp(user_email, xp_to_award):
    """
    Finds a user by email, awards them a specified amount of XP using the
    central award_xp function, and prints the result.
    """
    # The app_context is essential to connect to the database
    with app.app_context():
        # Find the user by their email address
        user = User.query.filter_by(email=user_email).first()

        if not user:
            print(f"❌ Error: User with email '{user_email}' not found.")
            return

        print(f"Found user: {user.username} (ID: {user.id})")
        print("-" * 30)

        # --- Display the user's state BEFORE the change ---
        print("--- BEFORE ---")
        print(f"Lifetime XP: {user.xp or 0}")
        print(f"Monthly XP: {user.monthly_xp or 0}")
        print(f"Tree Stage: {user.tree_stage or 0}")
        print(f"Last Reset Date: {user.last_xp_reset_date}")
        print("-" * 30)

        # --- Call the main award_xp function ---
        # This ensures all logic (monthly reset, tree growth) is applied
        award_xp(user, xp_to_award)

        # --- Commit the changes to the database ---
        try:
            db.session.commit()
            print(f"✅ Successfully awarded {xp_to_award} XP!")
            print("-" * 30)

            # --- Display the user's state AFTER the change ---
            print("--- AFTER ---")
            print(f"Lifetime XP: {user.xp or 0}")
            print(f"Monthly XP: {user.monthly_xp or 0}")
            print(f"Tree Stage: {user.tree_stage or 0}")
            print(f"Last Reset Date: {user.last_xp_reset_date}")
            print("-" * 30)

        except Exception as e:
            db.session.rollback()
            print(f"❌ An error occurred. Database changes have been rolled back. Error: {e}")

# This part of the script handles the command-line arguments
if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Award XP to a specific user to test gamification features.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "email",
        help="The email address of the user to award XP to."
    )
    parser.add_argument(
        "xp",
        type=int,
        help="The amount of XP to award (can be a positive or negative integer)."
    )

    args = parser.parse_args()

    run_award_xp(args.email, args.xp)