# reparse_all_lessons.py
from app import app, db, Lesson, _parse_and_save_lesson
import time

def reparse_all():
    with app.app_context():
        lessons_to_reparse = Lesson.query.all()
        total = len(lessons_to_reparse)
        print(f"Found {total} lessons to re-parse.")

        for i, lesson in enumerate(lessons_to_reparse):
            print(f"Processing ({i+1}/{total}): Lesson '{lesson.title}' (ID: {lesson.id})")
            try:
                # This function now contains your new outline and game logic
                _parse_and_save_lesson(lesson)
                db.session.commit()
                print("  -> Success.")
                # Delay to be kind to the AI API
                time.sleep(1) 
            except Exception as e:
                print(f"  -> FAILED to re-parse lesson {lesson.id}. Error: {e}")
                db.session.rollback()
        
        print("\nFinished re-parsing all lessons.")

if __name__ == '__main__':
    reparse_all()
