# Forcing a fresh deploy on Render - July 18

import os
import json
import uuid
import google.generativeai as genai
import cloudinary
import cloudinary.uploader
import cloudinary.api
from flask import Flask, request, render_template, jsonify, url_for, flash, redirect, session, abort
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.postgresql import JSONB
from flask_migrate import Migrate
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from dotenv import load_dotenv
import datetime
import pandas as pd
import numpy as np
from flask_wtf.csrf import CSRFProtect
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
import click
import hashlib
import re
import pytz
from sqlalchemy import func, cast, Date,extract,or_
import numpy as np 
import random

# --- Initialization ---
load_dotenv()
app = Flask(__name__)

@app.after_request
def add_header(response):
    """
    Add headers to prevent caching on dynamic API endpoints, while allowing
    caching for static assets and regular pages to improve performance.
    """
    # --- THIS IS THE FIX ---
    # We now prevent caching on more dynamic pages like the user profile and dashboard.
    path = request.path
    if (path.startswith('/chat') or path.startswith('/api') or
        path.startswith('/admin') or path.startswith('/user/') or path == '/dashboard'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    else:
        # Instruct the browser to cache all other pages and static assets for one week.
        response.headers['Cache-Control'] = 'public, max-age=604800'
    return response
    return response

# --- Cloudinary Configuration ---
cloudinary.config(
    cloud_name = os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key = os.getenv('CLOUDINARY_API_KEY'),
    api_secret = os.getenv('CLOUDINARY_API_SECRET'),
    secure=True
)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
oauth = OAuth(app)
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "a-strong-default-secret-key-for-dev")
app.config['WTF_CSRF_TIME_LIMIT'] = 14400 
DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL or 'sqlite:///coursewell.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp3', 'wav', 'ogg', 'mp4', 'webm', 'mov'}

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
migrate = Migrate(app, db)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

RAG_RETRIEVERS = {}

# --- Database Models ---
# Association table for the follow feature
follows = db.Table('follows',
    db.Column('follower_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('followed_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('timestamp', db.DateTime, default=datetime.datetime.utcnow)
)
class InteractiveGame(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(150), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    html_content = db.Column(db.Text, nullable=True)
    css_content = db.Column(db.Text, nullable=True)
    js_content = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=True)
    google_id = db.Column(db.String(120), unique=True, nullable=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    bio = db.Column(db.Text, nullable=True)
    links = db.Column(db.JSON, nullable=True)  # JSON for links
    games = db.relationship('InteractiveGame', backref='creator', lazy=True, cascade="all, delete-orphan")
    avatar_url = db.Column(db.String(255), default='/static/images/avatars/default.png')
    xp = db.Column(db.Integer, default=0) # This will now represent lifetime XP
    monthly_xp = db.Column(db.Integer, default=0)
    tree_stage = db.Column(db.Integer, default=0)
    last_xp_reset_date = db.Column(db.Date, nullable=True)
    guidelets = db.relationship('Guidelet', backref='creator', lazy=True, cascade="all, delete-orphan")
    theme = db.Column(db.String(20), nullable=False, default='light')
    streak_count = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    last_active_date = db.Column(db.Date, nullable=True)
    enrollments = db.relationship('Enrollment', back_populates='user', cascade="all, delete-orphan")
    is_creator = db.Column(db.Boolean, nullable=False, default=False, server_default='false')
    
    # --- FIXES APPLIED HERE ---
    reviews = db.relationship('Review', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    activities = db.relationship('Activity', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    notifications = db.relationship('Notification', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    daily_watch_times = db.relationship('DailyWatchTime', backref='user', lazy='dynamic', cascade="all, delete-orphan")
    # --- END OF FIXES ---

    # Follower relationships
    following = db.relationship(
        'User', secondary=follows,
        primaryjoin=(follows.c.follower_id == id),
        secondaryjoin=(follows.c.followed_id == id),
        backref=db.backref('followers', lazy='dynamic'),
        lazy='dynamic'
    )

    def is_following(self, user):
        return self.following.filter(follows.c.followed_id == user.id).count() > 0

    def follow(self, user):
        if not self.is_following(user):
            self.following.append(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.following.remove(user)

    def is_enrolled(self, guidelet):
        return any(enrollment.guidelet_id == guidelet.id for enrollment in self.enrollments)

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    guidelet_id = db.Column(db.String(36), db.ForeignKey('guidelet.id'), nullable=False)
    lesson_id = db.Column(db.String(36), db.ForeignKey('lesson.id'), nullable=False)
    
    # The original content from the tutor that was saved
    saved_content = db.Column(db.Text, nullable=False)
    
    # The user's personal comment on the saved content
    user_comment = db.Column(db.Text, nullable=True)
    
    # The key to the "View in Context" feature. This is the message's position in the chat history.
    message_index = db.Column(db.Integer, nullable=False)
    
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    # Add relationships for easy access
    user = db.relationship('User', backref=db.backref('notes', lazy='dynamic', cascade="all, delete-orphan"))
    guidelet = db.relationship('Guidelet', backref=db.backref('notes_taken', lazy='dynamic', cascade="all, delete-orphan"))
    lesson = db.relationship('Lesson', backref=db.backref('notes_taken', lazy='dynamic', cascade="all, delete-orphan"))

class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False) # e.g., 'enrolled', 'completed_chapter', 'completed_guidelet'
    guidelet_id = db.Column(db.String(36), db.ForeignKey('guidelet.id'), nullable=False)
    lesson_id = db.Column(db.String(36), db.ForeignKey('lesson.id'), nullable=True)
    xp_earned = db.Column(db.Integer, default=0)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.datetime.utcnow)

    guidelet = db.relationship('Guidelet', backref='activities')
    lesson = db.relationship('Lesson', backref='activities')

class Guidelet(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(150), nullable=False)
    status = db.Column(db.String(20), nullable=False, default='draft')
    is_published = db.Column(db.Boolean, nullable=False, default=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    enrollees = db.relationship('Enrollment', back_populates='guidelet', lazy=True, cascade="all, delete-orphan")
    lessons = db.relationship('Lesson', backref='guidelet', lazy=True, cascade="all, delete-orphan", order_by="Lesson.chapter_number")
    description = db.Column(db.Text, nullable=True)
    thumbnail_url = db.Column(db.String(255), nullable=True)
    reviews = db.relationship('Review', backref='guidelet', lazy=True, cascade="all, delete-orphan")
    shareable_link_id = db.Column(db.String(36), unique=True, nullable=True)
    category = db.Column(db.String(50), nullable=True) 
    notes = db.relationship('GuideletNote', backref='guidelet', lazy=True, cascade="all, delete-orphan")
    search_embedding = db.Column(db.Text, nullable=True)
    @property
    def average_rating(self):
        if not self.reviews: return 0
        return sum(r.rating for r in self.reviews) / len(self.reviews)

class Lesson(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.String(150), nullable=False)
    raw_script = db.Column(db.Text, nullable=False)
    editor_html = db.Column(db.Text, nullable=True)
    parsed_json = db.Column(db.Text, nullable=False)
    guidelet_id = db.Column(db.String(36), db.ForeignKey('guidelet.id'), nullable=False)
    chapter_number = db.Column(db.Integer, nullable=False)
    # THIS IS THE FIX: Add the relationship to ChatHistory with a cascade
    chat_histories = db.relationship('ChatHistory', backref='lesson', lazy='dynamic', cascade="all, delete-orphan")

class GuideletNote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    guidelet_id = db.Column(db.String(36), db.ForeignKey('guidelet.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    url = db.Column(db.String(255), nullable=False)

class Enrollment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    guidelet_id = db.Column(db.String(36), db.ForeignKey('guidelet.id'), nullable=False)
    last_completed_chapter_number = db.Column(db.Integer, default=0, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True, default=None)
    user = db.relationship('User', back_populates='enrollments')
    guidelet = db.relationship('Guidelet', back_populates='enrollees')
    chat_histories = db.relationship('ChatHistory', backref='enrollment', lazy='dynamic', cascade="all, delete-orphan")
    __table_args__ = (db.UniqueConstraint('user_id', 'guidelet_id', name='_user_guidelet_uc'),)

class ChatHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    enrollment_id = db.Column(db.Integer, db.ForeignKey('enrollment.id'), nullable=False)
    lesson_id = db.Column(db.String(36), db.ForeignKey('lesson.id'), nullable=False)
    history_json = db.Column(db.Text, nullable=False, default='[]')
    current_step_index = db.Column(db.Integer, nullable=False, default=0)
    current_chunk_index = db.Column(db.Integer, nullable=False, default=0)
    question_attempts = db.Column(db.JSON, nullable=True, default=lambda: {})
    __table_args__ = (db.UniqueConstraint('enrollment_id', 'lesson_id', name='_enrollment_lesson_uc'),)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    guidelet_id = db.Column(db.String(36), db.ForeignKey('guidelet.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'guidelet_id', name='_user_guidelet_review_uc'),)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, index=True, default=datetime.datetime.utcnow)
    # The conflicting user relationship has been removed from here.

# In app.py, with your other models

class MonthlyGrove(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    final_xp = db.Column(db.Integer, nullable=False)
    final_tree_stage = db.Column(db.Integer, nullable=False)

    user = db.relationship('User', backref=db.backref('monthly_groves', lazy='dynamic', cascade="all, delete-orphan"))

    __table_args__ = (db.UniqueConstraint('user_id', 'year', 'month', name='_user_year_month_uc'),)


# In app.py, with your other models...

class DailyWatchTime(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    guidelet_id = db.Column(db.String(36), db.ForeignKey('guidelet.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    seconds_watched = db.Column(db.Integer, default=0, nullable=False)

    guidelet = db.relationship('Guidelet', backref='daily_watch_times')
    # The conflicting user relationship has been removed from here as well.

    __table_args__ = (
        db.UniqueConstraint('user_id', 'guidelet_id', 'date', name='_user_guidelet_date_uc'),
    )
# Add this class with your other models like User, Guidelet, etc.
class TopicRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    topic_title = db.Column(db.String(150), nullable=False)
    details = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='new') # new, viewed, done
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) 
    
    # --- ADD THIS LINE ---
    # A field to store the session ID for anonymous users
    session_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    # Add a relationship back to the User model
    user = db.relationship('User', backref='topic_requests')




@app.context_processor
def inject_user_theme():
    if current_user.is_authenticated:
        return dict(user_theme=current_user.theme)
    # Default to light theme for logged-out users
    return dict(user_theme='light')

@login_manager.user_loader
def load_user(user_id):
    # The traceback indicates a misconfiguration with SQLAlchemy loader options.
    # The simplest and most robust way to load a user for the session is by
    # primary key using .get(), which avoids such issues. This ensures the
    # correct logic is in place.
    return User.query.get(int(user_id))

@app.context_processor
def inject_notifications():
    if current_user.is_authenticated:
        unread_notifications = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        return dict(unread_notifications=unread_notifications)
    return dict(unread_notifications=0)

@app.route('/api/set-theme', methods=['POST'])
@login_required
def set_theme():
    theme = request.json.get('theme')
    if theme in ['light', 'dark']:
        current_user.theme = theme
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Invalid theme'}), 400
def creator_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not (current_user.is_creator or current_user.is_admin):
            flash("You do not have permission to access the Creator Studio.", "danger")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# --- Prompts ---
PARSER_PROMPT = """
You are a precise curriculum parsing agent. Your task is to convert a teacher's lesson script into a structured JSON object. You MUST follow these rules exactly.
1. The final JSON object MUST have two top-level keys: "outline" and "steps".
2. The "outline" key MUST contain a concise list of the main topics or stages in the lesson, inferred from the script's structure.
3. Each object in the "steps" array MUST have a "type" key and a "stage" key. The "stage" value should be the corresponding topic from the "outline".
4. For explanatory text, the "type" should be "CONTENT" and it should have a "text" key. This includes any media placeholders like ---MEDIA_PLACEHOLDER---.
5. For multiple-choice questions like [QUESTION: ... OPTIONS: A)... ANSWER: B], a "type" of "QUESTION_MCQ" MUST be used. It MUST have a "question" key for the question text, an "options" key which is an array of strings, and an "answer" key.
6. For short-answer questions like [QUESTION_SA: ... KEYWORDS: word1, word2, ... REASON: (optional) ...], a "type" of "QUESTION_SA" MUST be used. It MUST have a "question" key for the question text and a "keywords" key which is an array of strings. If a "REASON" field is present, include it as an optional "reason" key in the JSON object.
 
 Parse the following script:
 """
INTENT_CLASSIFIER_PROMPT = """
You are an intent classification agent. Your task is to analyze a user's input during a lesson and determine their intent.
The user's input is: "{}"
The available media descriptions in this lesson are: {}

You MUST respond with a single, specific JSON object. Choose ONE of the following intents:

1.  If the user is asking a general question about the lesson content, respond with:
    {{"intent": "QNA", "query": "the user's original question"}}

2.  If the user is asking to see a specific piece of media again AND their request matches one of the available media descriptions, respond with:
    {{"intent": "MEDIA_REQUEST", "alt_text": "the matching media description from the list"}}

3.  If the user's request is unclear or doesn't fit the above, default to a general question:
    {{"intent": "QNA", "query": "the user's original question"}}

User Input: "{}"
"""
DEFAULT_TUTOR_PERSONA = "You are a friendly, and helpful AI tutor. You are guiding a student through an interactive online guidelet."

SA_ANALYSIS_PROMPT = """
You are an AI assistant that evaluates a student's answer to a short-answer question.
The user was asked: "{question}"
The expected concepts or keywords are: {keywords}
The user's answer is: "{answer}"

Analyze the user's answer. Respond with a single JSON object with two keys:
1.  "is_correct": a boolean value (true if the user's answer includes the keywords/concepts, false otherwise).
2.  "feedback": a short, encouraging feedback message for the student. If the answer is incorrect, provide a hint to guide them.
"""

# NEW: This prompt is used when the user answers correctly AND a reason is provided.
SA_CORRECT_WITH_REASON_PROMPT = """
The student correctly answered the question: "{question}"
Your task is to now explain the reasoning behind the answer. Use the following notes from the lesson creator to provide a clear, encouraging, and well-formatted step-by-step explanation. Polish the language and present it in a natural, conversational way. Use markdown for formatting, like bolding or numbered lists.

Creator's notes:
"{reason}"
"""

# --- Helper Functions & Decorators ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
def _clean_editor_html(html_content):
    """
    Uses regex to remove the entire div containers for media previews
    (which contain blob: URLs) before saving to the database.
    """
    if not html_content:
        return ''
    
    # This pattern looks for <div contenteditable="false" ...> ... </div>
    # and removes the entire block. It's designed to target the preview
    # containers created by create.js.
    pattern = re.compile(r'<div class="(?:image-container|audio-preview|video-preview)".*?<\/div>', re.DOTALL)
    
    cleaned_html = pattern.sub('', html_content)
    return cleaned_html

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("You do not have permission to access this page.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function
# In app.py

def award_xp(user, amount):
    """
    Awards XP, checks for monthly resets, and SAVES the previous month's grove to history.
    """
    today = datetime.datetime.utcnow().date()
    
    # --- START: NEW HISTORY-SAVING LOGIC ---
    # Check if a reset is needed (first activity in a new month)
    if user.last_xp_reset_date and (user.last_xp_reset_date.year < today.year or user.last_xp_reset_date.month < today.month):
        # Before resetting, check if the previous month's tree is worth saving (Stage 1 or higher)
        if user.tree_stage and user.tree_stage >= 1:
            # Check if a record for that month already exists to be safe
            existing_grove = MonthlyGrove.query.filter_by(
                user_id=user.id,
                year=user.last_xp_reset_date.year,
                month=user.last_xp_reset_date.month
            ).first()

            if not existing_grove:
                new_grove_record = MonthlyGrove(
                    user_id=user.id,
                    year=user.last_xp_reset_date.year,
                    month=user.last_xp_reset_date.month,
                    final_xp=user.monthly_xp,
                    final_tree_stage=user.tree_stage
                )
                db.session.add(new_grove_record)
        
        # Now, perform the reset
        user.monthly_xp = 0
        user.tree_stage = 0
    # --- END: NEW HISTORY-SAVING LOGIC ---

    # If it's the user's very first activity, set the date
    if user.last_xp_reset_date is None:
        user.last_xp_reset_date = today

    # Award the XP
    user.xp = (user.xp or 0) + amount
    user.monthly_xp = (user.monthly_xp or 0) + amount
    
    # Update last active date (for streak logic, unrelated but good to have)
    user.last_active_date = today

    # Tree stage logic remains the same
    xp_thresholds = [100, 250, 500, 800, 1200, 1700, 2300, 3000, 4000, 5000]
    new_stage = 0
    for i, threshold in enumerate(xp_thresholds):
        if user.monthly_xp >= threshold:
            new_stage = i + 1
    user.tree_stage = min(new_stage, 10)

    db.session.add(user)

def _parse_and_save_lesson(lesson):
    """
    Parses the lesson's raw_script into a structured JSON using a more robust, context-aware method.
    """
    print(f"--- Starting SMART parsing for Lesson ID: {lesson.id} ---")
    try:
        # 1. PRE-PROCESSING: Separate media/game tags from the main text content.
        # This pattern finds ONLY media and game tags, leaving question tags for the AI to parse.
        media_game_pattern = re.compile(r'(\[(?:IMAGE|AUDIO|VIDEO|INTERACTIVE_GAME):.*?\])', re.DOTALL)
        
        # Extract the media/game tags so we can re-insert their data later.
        media_game_tags_found = media_game_pattern.findall(lesson.raw_script)
        
        # Create a clean text version for the AI. Question tags like [QUESTION_SA:...] will REMAIN in this text.
        text_for_ai = media_game_pattern.sub('---MEDIA_PLACEHOLDER---', lesson.raw_script)

        # Get existing media URLs from the current parsed_json to preserve them during an update.
        existing_media_map = {}
        if lesson.parsed_json:
            try:
                old_data = json.loads(lesson.parsed_json)
                for step in old_data.get('steps', []):
                    if step.get('type') == 'MEDIA' and step.get('id') and step.get('media_url'):
                        existing_media_map[step['id']] = { "url": step['media_url'], "type": step.get('media_type', 'image') }
            except (json.JSONDecodeError, AttributeError):
                 print(f"Warning: Could not parse existing JSON for lesson {lesson.id}.")

        # 2. AI PARSING: Send the text (with question tags intact) to the AI for structuring.
        print(f"Sending text with question tags to AI for structuring...")
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(PARSER_PROMPT + text_for_ai)
        cleaned_response = response.text.strip().replace("```json", "").replace("```", "").strip()
        ai_parsed_data = json.loads(cleaned_response)
        
        # 3. REASSEMBLY: Merge the AI's structured text/questions with our extracted media tags.
        final_steps = []
        media_tag_index = 0
        for step in ai_parsed_data.get('steps', []):
            # If the AI identified a question, add it directly.
            if step.get('type') in ['QUESTION_MCQ', 'QUESTION_SA']:
                final_steps.append(step)
                continue

            # If the step is regular content, check for our media placeholders.
            if step.get('type') == 'CONTENT':
                text_content = step.get('text', '')
                text_chunks = text_content.split('---MEDIA_PLACEHOLDER---')
                
                # Add the text part before the first placeholder.
                if text_chunks[0].strip():
                    final_steps.append({"type": "CONTENT", "text": text_chunks[0].strip(), "stage": step.get('stage')})

                # Loop through the placeholders and re-insert the media/game data.
                for i in range(len(text_chunks) - 1):
                    if media_tag_index < len(media_game_tags_found):
                        tag_to_process = media_game_tags_found[media_tag_index]
                        
                        game_match = re.fullmatch(r'\[INTERACTIVE_GAME: id="([a-f0-9\-]+)" title="(.*?)"\]', tag_to_process)
                        media_match = re.fullmatch(r'\[(IMAGE|AUDIO|VIDEO):.*?description="(.*?)".*?id="(.*?)".*?\]', tag_to_process, re.DOTALL)

                        if game_match:
                            final_steps.append({"type": "INTERACTIVE_GAME", "game_id": game_match.groups()[0], "title": game_match.groups()[1], "stage": step.get('stage')})
                        elif media_match:
                            tag_type, description, media_id = media_match.groups()
                            media_info = existing_media_map.get(media_id, {})
                            final_steps.append({"type": "MEDIA", "media_type": media_info.get('type', tag_type.lower()), "alt_text": description, "id": media_id, "media_url": media_info.get('url'), "stage": step.get('stage')})
                        
                        media_tag_index += 1
                    
                    # Add the text that came after this placeholder.
                    if text_chunks[i+1].strip():
                        final_steps.append({"type": "CONTENT", "text": text_chunks[i+1].strip(), "stage": step.get('stage')})
            else:
                # If the AI generates some other type of step, pass it through.
                final_steps.append(step)
        
        # 4. POST-PROCESSING: Generate outline with icons.
        outline_stages = ai_parsed_data.get('outline', [])
        icon_map = {}
        if outline_stages:
            try:
                icon_prompt = f"""
                For each topic in the following list, provide a single, relevant emoji icon that represents it.
                Return ONLY a valid JSON object where keys are the topic names and values are the emoji strings.
                Example: {{"Introduction to Physics": "⚛️", "Final Quiz": "🏆"}}

                Topics: {json.dumps(outline_stages)}
                """
                model = genai.GenerativeModel('gemini-1.5-flash')
                response = model.generate_content(icon_prompt)
                cleaned_response = response.text.strip().replace("```json", "").replace("```", "").strip()
                icon_map = json.loads(cleaned_response)
            except (json.JSONDecodeError, Exception) as e:
                print(f"Warning: Could not generate icons for outline. Will use defaults. Error: {e}")
                icon_map = {}

        final_outline = [{"stage": stage, "icon": icon_map.get(stage, '💎')} for stage in outline_stages]        

        # 5. FINALIZE and save to the lesson object.
        lesson.parsed_json = json.dumps({"outline": final_outline, "steps": final_steps})
        print(f"--- Successfully completed parsing for Lesson ID: {lesson.id} ---")

    except Exception as e:
        print(f"FATAL ERROR during SMART parsing for lesson {lesson.id}: {e}")
        raise


def parse_lesson_script(script_text):
    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(PARSER_PROMPT + script_text)
        cleaned_response = response.text.strip().replace("```json", "").replace("```", "").strip()
        parsed_json = json.loads(cleaned_response)
        return parsed_json if isinstance(parsed_json, dict) and 'steps' in parsed_json else None
    except Exception as e:
        print(f"Error during parsing: {e}")
        return None

def get_tutor_response(full_prompt):
    try:
        print("\n" + "="*80)
        print("--- PROMPT SENT TO GEMINI: ---")
        print(full_prompt)
        print("="*80 + "\n")
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(full_prompt)
        response_text = response.text if response.text else "Let's try that another way."
        print("\n" + "-"*80)
        print("--- RESPONSE RECEIVED FROM GEMINI: ---")
        print(response_text)
        print("-"*80 + "\n")
        return response_text
    except Exception as e:
        print(f"Error getting tutor response: {e}")
        return "I seem to be having a little trouble thinking. Could you try again."

def generate_and_save_embedding(guidelet):
    """Generates a search embedding for a guidelet and saves it."""
    if not guidelet.title and not guidelet.description:
        guidelet.search_embedding = None
        return

    # Combine title and description for richer context
    content_to_embed = f"Title: {guidelet.title}\n\nDescription: {guidelet.description}"
    
    try:
        # Use Gemini's embedding model
        embedding_result = genai.embed_content(
            model='models/text-embedding-004',
            content=content_to_embed,
            task_type="RETRIEVAL_DOCUMENT"
        )
        # Store the list of numbers as a JSON string
        guidelet.search_embedding = json.dumps(embedding_result['embedding'])
        print(f"Successfully generated embedding for guidelet: {guidelet.id}")
    except Exception as e:
        print(f"Error generating embedding for guidelet {guidelet.id}: {e}")
        guidelet.search_embedding = None


@app.route('/generate-caption', methods=['POST'])
@login_required
def generate_caption():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and allowed_file(file.filename):
        try:
            # Prepare the image for the Vision API
            image_parts = [
                {
                    "mime_type": file.content_type,
                    "data": file.read()
                }
            ]
            
            # Prepare the prompt
            prompt_parts = [
                "Analyze this image in detail. Provide a comprehensive description that captures the key objects, their attributes, their relationships, and the overall context. This description will be used as context for an AI tutor teaching a lesson, so focus on details that would be relevant for educational purposes. For example, instead of 'a diagram', say 'a diagram showing the Krebs cycle with labels for each stage'. Instead of 'a person', say 'a scientist in a lab coat holding a test tube'.",
                image_parts[0]
            ]
            
            # Call the Gemini Vision API
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(prompt_parts)
            
            # Clean up the response text
            caption = response.text.strip().replace('\n', ' ')
            
            return jsonify({'caption': caption})

        except Exception as e:
            print(f"Error generating caption: {e}")
            return jsonify({'error': 'Failed to generate caption'}), 500
            
    return jsonify({'error': 'Invalid file type'}), 400

def _get_or_create_rag_retriever(lesson_id, lesson_script):
    script_hash = hashlib.sha256(lesson_script.encode()).hexdigest()

    if lesson_id in RAG_RETRIEVERS:
        cached_data = RAG_RETRIEVERS[lesson_id]
        if cached_data.get('hash') == script_hash:
            return cached_data.get('retriever')

    # Remove question tags and split into paragraphs for cleaner context
    script_no_questions = re.sub(r'\[QUESTION.*?\]', '', lesson_script)
    text_chunks = [chunk.strip() for chunk in script_no_questions.split('\n') if chunk.strip()]
    
    if not text_chunks: 
        return None
    
    try:
        print(f"Creating new RAG retriever for lesson {lesson_id}...")
        embeddings = genai.embed_content(model='models/text-embedding-004', content=text_chunks, task_type="RETRIEVAL_DOCUMENT")['embedding']
        df = pd.DataFrame(text_chunks, columns=['text'])
        df['embeddings'] = embeddings
        
        RAG_RETRIEVERS[lesson_id] = {
            'hash': script_hash,
            'retriever': df
        }
        print(f"RAG retriever created and cached for lesson {lesson_id}.")
        return df
    except Exception as e:
        print(f"Error creating RAG embeddings: {e}")
        return None

def answer_question_with_full_context(question, lesson, chat_history):
    """
    Answers a user's question using the full lesson script as context.
    This replaces the RAG approach for higher accuracy on shorter documents.
    """
    full_lesson_script = lesson.raw_script

    # Get the last 8 messages (4 turns) for conversational context.
    history_for_answer = "\n".join([f"{msg['sender'].title()}: {msg['content']}" for msg in chat_history[-8:] if msg.get('type') == 'text'])

    # THIS IS THE FIX: The prompt instructions are now more explicit.
    prompt = f"""You are a helpful and friendly AI tutor. Your primary goal is to help the student learn.

[RECENT CONVERSATION HISTORY]
{history_for_answer}
Student: {question}

[FULL LESSON SCRIPT]
---
{full_lesson_script}
---

INSTRUCTIONS:
1.  Thoroughly analyze the [RECENT CONVERSATION HISTORY] to understand the student's current question.
2.  **CRITICAL RULE:** If the student's question is ambiguous or a conversational follow-up (e.g., "why?", "tell me more", "another one?"), you **MUST** assume they are referring to the immediate topic of the Tutor's most recent message in the history.
3.  Consult the [FULL LESSON SCRIPT] to find the definitive answer or relevant information related to that topic.
4.  Formulate a clear, helpful, and conversational response based **strictly** on the information found in the lesson script.
5.  If the script does not contain the answer, explicitly state that the topic is not covered in the lesson material. Then explain it in detail (using outside knowledge)

"""
    return get_tutor_response(prompt)



def log_activity(user, action, guidelet, lesson=None, xp_earned=0):
    """Logs user activity, awards XP, and updates the daily streak."""
  
    if xp_earned > 0:
        user.xp = (user.xp or 0) + xp_earned
        
        # --- NEW: STREAK CALCULATION LOGIC ---
        today = datetime.datetime.utcnow().date()
        
        # If the user was active before, check the dates
        if user.last_active_date:
            days_since_last_active = (today - user.last_active_date).days
            
            # Case 1: Streak Continues! They were active yesterday.
            if days_since_last_active == 1:
                user.streak_count = (user.streak_count or 0) + 1
            # Case 2: Streak is Broken. They were active more than a day ago.
            elif days_since_last_active > 1:
                user.streak_count = 1 # Reset to a new 1-day streak
            # Case 3: Same Day. Do nothing to the streak count.
            
        else:
            # First time this user is earning XP. Start their streak.
            user.streak_count = 1

        # Always update the last active date to today
        user.last_active_date = today
        # --- END NEW ---

        db.session.add(user)
    
    # Create the corresponding activity log for the graph
    activity = Activity(
        user_id=user.id,
        action=action,
        guidelet_id=guidelet.id,
        lesson_id=lesson.id if lesson else None,
        xp_earned=xp_earned
    )
    db.session.add(activity)


def _replace_media_tags_for_prompt(text_content):
    """
    Replaces [IMAGE:...] and [AUDIO:...] tags with a natural language placeholder
    for the AI prompt, preventing the AI from literally outputting the tag.
    """
    def replacer(match):
        tag_type = match.group(1).capitalize() # 'IMAGE' -> 'Image'
        description_match = re.search(r'(?:alt|description)="(.*?)"', match.group(0))
        description = description_match.group(1) if description_match else "a media element"
        return f"\n[The student was shown an {tag_type} with the description: \"{description}\"]\n"

    return re.sub(r'\[(IMAGE|AUDIO|VIDEO):.*?\]', replacer, text_content)


# --- Admin Routes ---
@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    pending_guidelets = Guidelet.query.filter_by(status='pending_review').all()
    published_guidelets = Guidelet.query.filter_by(status='published').all()
    all_users = User.query.order_by(User.email).all()
    topic_requests = TopicRequest.query.order_by(TopicRequest.created_at.desc()).all()

    return render_template('admin_dashboard.html', 
                           pending_guidelets=pending_guidelets, 
                           published_guidelets=published_guidelets,
                           all_users=all_users,topic_requests=topic_requests)

@app.route('/admin/guidelet/<string:guidelet_id>/decide', methods=['POST'])
@login_required
@admin_required
def decide_guidelet(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    decision = request.form.get('decision')
    if decision == 'approve':
        guidelet.status = 'published'
        guidelet.is_published = True
        flash(f"Guidelet '{guidelet.title}' has been approved and published.", 'success')
        # Notify creator of approval
        notification = Notification(
            user_id=guidelet.user_id,
            message=f"Congratulations! Your guidelet, '{guidelet.title}', has been approved and is now live."
        )
        db.session.add(notification)
    elif decision == 'reject':
        rejection_reason = request.form.get('rejection_reason')
        if not rejection_reason:
            flash("A reason is required to reject a guidelet.", 'danger')
            return redirect(url_for('admin_dashboard'))
        guidelet.status = 'rejected'
        guidelet.is_published = False
        flash(f"Guidelet '{guidelet.title}' has been rejected and returned to the creator.", 'warning')
        # Notify creator of rejection with reason
        notification = Notification(
            user_id=guidelet.user_id,
            message=f"Your guidelet, '{guidelet.title}', has been rejected. Reason: {rejection_reason}"
        )
        db.session.add(notification)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/guidelet/<string:guidelet_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_guidelet(guidelet_id):
    """Allows an admin to delete any guidelet directly."""
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    guidelet_title = guidelet.title
    
    # Manually clear RAG cache for lessons in this guidelet if they exist
    for lesson in guidelet.lessons:
        if lesson.id in RAG_RETRIEVERS:
            del RAG_RETRIEVERS[lesson.id]
            
    db.session.delete(guidelet)
    db.session.commit()
    flash(f"Guidelet '{guidelet.title}' has been permanently deleted by an admin.", 'success')
    return redirect(url_for('explore'))

@app.route('/admin/review/<int:review_id>/delete', methods=['POST'])
@login_required
@admin_required
def admin_delete_review(review_id):
    """Allows an admin to delete a specific review."""
    review = Review.query.get_or_404(review_id)
    db.session.delete(review)
    db.session.commit()
    flash('Review has been successfully deleted.', 'success')
    return redirect(request.referrer or url_for('admin_dashboard'))


# In /app.py, near the other @app.cli.command functions

@app.cli.command("creator")
@click.argument("action")
@click.argument("email")
def creator_command(action, email):
    """Grants or revokes creator privileges for a user."""
    user = User.query.filter_by(email=email).first()
    if not user:
        print(f"Error: User with email '{email}' not found.")
        return

    if action == "grant":
        user.is_creator = True
        db.session.commit()
        print(f"Success: {user.username} ({email}) has been granted creator privileges.")
    elif action == "revoke":
        user.is_creator = False
        db.session.commit()
        print(f"Success: {user.username} ({email}) has had their creator privileges revoked.")
    else:
        print(f"Error: Unknown action '{action}'. Use 'grant' or 'revoke'.")

# --- AUTHENTICATION ROUTES ---
@app.route('/login')
def login():
    redirect_uri = url_for('authorize', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@app.route('/auth/callback/google')
def authorize():
    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get('userinfo')
    except Exception as e:
        flash(f"Authentication failed: {e}", 'danger')
        return redirect(url_for('index'))
    if userinfo:
        google_id = userinfo['sub']
        email = userinfo['email']
        name = userinfo['name']
        user = User.query.filter_by(google_id=google_id).first()
        if not user:
            # Don't set a username on creation. Force the user to claim one.
            user = User(google_id=google_id, email=email, username=None)
            db.session.add(user)
            db.session.commit()
        login_user(user, remember=True)
        next_page = session.pop('next', None)

        # Check if the user needs to claim a username
        if not user.username:
            # If they were trying to go somewhere specific, save it for after they claim a username
            if next_page:
                session['next_after_claim'] = next_page
            # Force them to the claim username page
            return redirect(url_for('claim_username'))
        # If they already have a username, proceed as normal
        return redirect(next_page or url_for('dashboard'))
    flash('Authentication failed.', 'danger')
    return redirect(url_for('index'))

@app.route('/logout', methods=['POST'])
def logout():
    logout_user()
    return redirect(url_for('explore'))

# --- Core App Routes ---
@app.route('/')
def index():
    return redirect(url_for('explore'))

@app.route('/about')
def about():
    return render_template('about.html')
@app.route('/admin/topic-request/<int:request_id>/update_status', methods=['POST'])
@login_required
@admin_required
def update_topic_request_status(request_id):
    topic_request = TopicRequest.query.get_or_404(request_id)
    new_status = request.form.get('status')
    if new_status in ['new', 'viewed', 'done']:
        topic_request.status = new_status
        db.session.commit()
        flash(f"Request '{topic_request.topic_title}' status updated to {new_status}.", 'success')
    else:
        flash("Invalid status.", 'danger')
    return redirect(url_for('admin_dashboard'))


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

@app.route('/terms')
def terms():
    return render_template('terms.html')
# Add this new route somewhere in app.py

@app.route('/request-topic', methods=['GET', 'POST'])
@login_required
def request_topic():
    search_query = request.args.get('q', '')
    if request.method == 'POST':
        title = request.form.get('topic_title')
        details = request.form.get('details')

        if not title:
            flash('A topic title is required.', 'warning')
            return redirect(url_for('request_topic'))

        new_request = TopicRequest(
            topic_title=title,
            details=details,
            user_id=current_user.id
        )
        db.session.add(new_request)
        db.session.commit()

        flash('Thank you! Your topic request has been submitted.', 'success')
        return redirect(url_for('explore'))

    return render_template('request_topic.html', search_query=search_query)

@app.route('/chat/intent', methods=['POST'])
@login_required
def classify_intent():
    data = request.json
    user_input = data.get('user_input')
    lesson_id = data.get('lesson_id')
    lesson = Lesson.query.get_or_404(lesson_id)
    lesson_steps = json.loads(lesson.parsed_json).get('steps', [])
    media_descriptions = [step.get('alt_text') for step in lesson_steps if step.get('type') == 'MEDIA' and step.get('alt_text')]
    prompt = INTENT_CLASSIFIER_PROMPT.format(user_input, media_descriptions, user_input)
    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)
        cleaned_response = response.text.strip().replace("```json", "").replace("```", "").strip()
        intent_data = json.loads(cleaned_response)
        return jsonify(intent_data)
    except Exception as e:
        print(f"Error classifying intent: {e}")
        return jsonify({"intent": "QNA", "query": user_input})


@app.route('/chat', methods=['POST'])
@login_required
def chat():
    data = request.json
    lesson_id = data.get('lesson_id')
    user_input = data.get('user_input')
    request_type = data.get('request_type', 'LESSON_FLOW')
    
    MAX_PREVIEW_LOG_LENGTH = 10  # Cap the preview log to 10 entries (5 turns)

    lesson = Lesson.query.get_or_404(lesson_id)
    lesson_data = json.loads(lesson.parsed_json)
    lesson_steps = lesson_data.get('steps', [])
    lesson_outline = lesson_data.get('outline', [])

    enrollment = Enrollment.query.filter_by(
        user_id=current_user.id, 
        guidelet_id=lesson.guidelet_id
    ).first()

    session_key = f'chat_session_{lesson_id}'
    if session_key not in session:
        session[session_key] = {}

    # Handle persona setting
    if user_input and user_input.lower().startswith("set persona:"):
        new_persona = user_input[len("set persona:"):].strip()
        session[session_key]['persona'] = new_persona
        session.modified = True
        return jsonify({
            "tutor_text": f"Okay, I will now act as: {new_persona}",
            "is_system_message": True
        })
    elif user_input and user_input.lower() == "reset persona":
        session[session_key].pop('persona', None)
        session.modified = True
        return jsonify({
            "tutor_text": "My persona has been reset to the default. How can I help you?",
            "is_system_message": True
        })

    # Get persona from session, or default
    persona = session.get(session_key, {}).get('persona', DEFAULT_TUTOR_PERSONA)

    if request_type == 'MEDIA_REQUEST':
        requested_alt_text = user_input
        media_to_show = next((
            step for step in lesson_steps 
            if step.get('type') == 'MEDIA' and step.get('alt_text') == requested_alt_text
        ), None)
        
        if media_to_show:
            return jsonify({
                "tutor_text": f"Of course, here is '{media_to_show.get('alt_text')}' again.",
                "media_url": media_to_show.get('media_url'),
                "media_type": media_to_show.get('media_type'),
                "is_qna_response": True
            })
        else:
            request_type = 'QNA'

    is_creator = (current_user.id == lesson.guidelet.user_id)
    if not enrollment and not is_creator and not current_user.is_admin:
        abort(403, "Forbidden")

    history_record = None
    step_index, chunk_index, chat_log = 0, 0, []

    if enrollment:
        history_record = ChatHistory.query.filter_by(
            enrollment_id=enrollment.id, 
            lesson_id=lesson.id
        ).first()

        if history_record:
            step_index = history_record.current_step_index
            chunk_index = history_record.current_chunk_index
            chat_log = list(json.loads(history_record.history_json))
        else:
            history_record = ChatHistory(
                enrollment_id=enrollment.id, 
                lesson_id=lesson.id
            )
            db.session.add(history_record)
    else:  # Preview mode for creator/admin
        preview_session_key = f'preview_chat_{lesson_id}'
        session_data = session.get(preview_session_key, {
            'step_index': 0, 
            'chunk_index': 0
        })
        step_index, chunk_index = session_data['step_index'], session_data['chunk_index']

    if user_input and request_type == 'LESSON_FLOW' and user_input != 'Continue':
        chat_log.append({
            "sender": "student", 
            "type": "text", 
            "content": user_input
        })

    if request_type == 'QNA':
        # Pass the current chat log to provide conversational context
        response_text = answer_question_with_full_context(user_input, lesson, chat_log)

        chat_log.append({
            "sender": "student", 
            "type": "text", 
            "content": user_input
        })
        chat_log.append({
            "sender": "tutor", 
            "type": "text", 
            "content": response_text
        })

        if history_record:
            history_record.history_json = json.dumps(chat_log)
        db.session.commit()
        return jsonify({
            'is_qna_response': True, 
            'tutor_text': response_text
        })

    response_data = {}
    model_response_text = ""
    next_step_index, next_chunk_index = step_index, chunk_index

    task_description = ""
    state_description = ""

    if step_index >= len(lesson_steps):
        state_description = "The student has successfully completed all learning material in this chapter."
        task_description = "Conclude the chapter enthusiastically. Congratulate the student and let them know the system will guide them to the next step."
        response_data['is_lesson_end'] = True
        
        if enrollment:
            if enrollment.last_completed_chapter_number < lesson.chapter_number:
                enrollment.last_completed_chapter_number = lesson.chapter_number
                award_xp(current_user, 100)
                log_activity(
                    current_user, 
                    'completed_chapter', 
                    lesson.guidelet, 
                    lesson, 
                    xp_earned=100
                )
                response_data['xp_earned'] = 100

            if lesson.chapter_number >= len(lesson.guidelet.lessons):
                if not enrollment.completed_at: 
                    enrollment.completed_at = datetime.datetime.utcnow()
                    award_xp(current_user, 500)
                    log_activity(
                        current_user, 
                        'completed_guidelet', 
                        lesson.guidelet, 
                        xp_earned=500
                    )
                    response_data['xp_earned'] = 500
                    response_data['certificate_url'] = url_for(
                    'certificate_view', 
                    guidelet_id=lesson.guidelet.id
                )
            else:
                next_chapter_num = lesson.chapter_number + 1
                response_data['next_chapter_url'] = url_for(
                    'student_chapter_view', 
                    guidelet_id=lesson.guidelet.id, 
                    chapter_number=next_chapter_num
                )
    else:
        # This is the main lesson flow logic
        if user_input is None:  # It's the start of the lesson
            current_step = lesson_steps[step_index]
            step_type = current_step.get('type')

            if step_type == 'INTERACTIVE_GAME':
                response_data['interactive_game'] = {
                    'game_id': current_step.get('game_id'), 
                    'title': current_step.get('title')
                }
                next_step_index = step_index + 1
                if enrollment:
                    history_record.current_step_index = next_step_index
                else:
                    session[f'preview_chat_{lesson_id}'] = {
                        'step_index': next_step_index, 
                        'chunk_index': 0
                    }
                    session.modified = True
                db.session.commit()
                return jsonify(response_data)
            
            elif step_type == 'CONTENT':
                chunk_to_explain = "\n\n".join([
                    s.get('text', '') for s in lesson_steps 
                    if s.get('type') == 'CONTENT' and s.get('stage') == current_step.get('stage')
                ])
                
                if lesson.chapter_number > 1:
                    task_description = f"The student is starting Chapter {lesson.chapter_number}. **Start by welcoming them back to the guidelet and then introduce the first topic of this new chapter.** The content to explain is:\n---\n{_replace_media_tags_for_prompt(chunk_to_explain)}\n---"
                    state_description = f"The student is starting Chapter {lesson.chapter_number}."
                else:
                    task_description = f"The student is just beginning this guidelet. **Start with a warm welcome and then introduce the very first topic.** The content to explain is:\n---\n{_replace_media_tags_for_prompt(chunk_to_explain)}\n---"
                    state_description = "The student is at the very beginning of the guidelet."
                next_step_index = step_index + 1
                
            elif step_type == 'MEDIA':
                media_type = current_step.get('media_type', 'image')
                alt_text = current_step.get('alt_text', f'a {media_type}')
                media_url = current_step.get('media_url')
                
                if media_url:
                    response_data['media_url'] = media_url
                    response_data['media_type'] = media_type
                else:
                    print(f"WARNING: Media step has null URL at step {step_index} in lesson {lesson.id}")
                
                explanation_instruction = f"The student has just been shown a {media_type}. Now, explain the concepts in the following text, which describes the media. The content to explain is:\n---\n{alt_text}\n---"
                
                if lesson.chapter_number > 1:
                    intro_phrase = f"The student is starting Chapter {lesson.chapter_number}, which begins with a {media_type}. Welcome them back to the guidelet and then proceed with the explanation of the media's content."
                else:  # Very first chapter
                    intro_phrase = f"The student is just beginning this guidelet with a {media_type}. Start with a warm welcome and then proceed with the explanation of the media's content."
                
                task_description = f"{intro_phrase}\n\n{explanation_instruction}"
                state_description = f"The student is ready for the next piece of content, which is a {media_type}."
                next_step_index = step_index + 1
        else:
            current_step = lesson_steps[step_index]
            step_type = current_step.get('type')

            if step_type == 'INTERACTIVE_GAME':
                response_data['interactive_game'] = {
                    'game_id': current_step.get('game_id'), 
                    'title': current_step.get('title')
                }
                next_step_index = step_index + 1
                if enrollment:
                    history_record.current_step_index = next_step_index
                    history_record.history_json = json.dumps(chat_log)
                else:
                    session[f'preview_chat_{lesson_id}'] = {
                        'step_index': next_step_index, 
                        'chunk_index': 0
                    }
                    session.modified = True
                db.session.commit()
                return jsonify(response_data)
            
            elif step_type == 'CONTENT':
                content_to_explain = []
                next_step_index = step_index
                
                while next_step_index < len(lesson_steps):
                    step = lesson_steps[next_step_index]
                    if (step.get('type') == 'CONTENT' and 
                        step.get('stage') == current_step.get('stage')):
                        content_to_explain.append(step.get('text', ''))
                        next_step_index += 1
                    else:
                        break
                
                chunk_to_explain = "\n\n".join(content_to_explain)
                processed_chunk_to_explain = _replace_media_tags_for_prompt(chunk_to_explain)

                if step_index == 0:
                    if lesson.chapter_number > 1:
                        task_description = f"The student is starting Chapter {lesson.chapter_number}. **Start by welcoming them back to the guidelet and then introduce the first topic of this new chapter.** The content to explain is:\n---\n{processed_chunk_to_explain}\n---"
                        state_description = f"The student is starting Chapter {lesson.chapter_number}."
                    else:
                        task_description = f"The student is just beginning this guidelet. **Start with a warm welcome and then introduce the very first topic.** The content to explain is:\n---\n{processed_chunk_to_explain}\n---"
                        state_description = "The student is at the very beginning of the guidelet."
                else:
                    state_description = "The student is continuing the lesson and is ready for the next piece of content."
                    task_description = f"Present the next piece of information as a natural continuation of the conversation. The content to explain is:\n---\n{processed_chunk_to_explain}\n---"
                
                next_chunk_index = 0
                if enrollment and random.random() < 0.15:
                    xp_to_award = 5 # A small, delightful bonus
                    award_xp(current_user, xp_to_award)
                    log_activity(
                        current_user,
                        'random_progress_xp',
                        lesson.guidelet,
                        lesson,
                        xp_earned=xp_to_award
                    )
                    response_data['xp_earned'] = xp_to_award

            else:
                if step_type == 'MEDIA':
                    media_type = current_step.get('media_type', 'image')
                    alt_text = current_step.get('alt_text', f'a {media_type}')
                    media_url = current_step.get('media_url')
                    
                    if media_url:
                        response_data['media_url'] = media_url
                        response_data['media_type'] = media_type
                    else:
                        print(f"WARNING: Media step has null URL at step {step_index} in lesson {lesson.id}")

                    explanation_instruction = f"The student has just been shown a {media_type}. Now, explain the concepts in the following text, which describes the media. Present this as a natural continuation of the conversation. The content to explain is:\n---\n{alt_text}\n---"
                    
                    if step_index == 0:
                        if lesson.chapter_number > 1:
                            intro_phrase = f"The student is starting Chapter {lesson.chapter_number}, which begins with a {media_type}. Welcome them back to the guidelet and then proceed with the explanation of the media's content."
                            state_description = f"The student is starting Chapter {lesson.chapter_number} with a {media_type}."
                        else:
                            intro_phrase = f"The student is just beginning this guidelet with a {media_type}. Start with a warm welcome and then proceed with the explanation of the media's content."
                            state_description = f"The student is at the very beginning of the guidelet, which starts with a {media_type}."
                        task_description = f"{intro_phrase}\n\n{explanation_instruction}"
                    else:
                        state_description = f"The student is continuing the lesson and is ready for the next piece of content, which is a {media_type}."
                        task_description = explanation_instruction
                    next_step_index = step_index + 1
                    next_chunk_index = 0
                    
                elif step_type in ['QUESTION_MCQ', 'QUESTION_SA']:
                    question_id = f"step_{step_index}"
                    
                    if user_input and user_input != 'Continue':
                        attempts = (history_record.question_attempts.get(question_id, 0) 
                                  if history_record and history_record.question_attempts else 0)
                        
                        if history_record:
                            if history_record.question_attempts is None: 
                                history_record.question_attempts = {}
                            history_record.question_attempts[question_id] = attempts + 1
                            from sqlalchemy.orm.attributes import flag_modified
                            flag_modified(history_record, "question_attempts")

                        if step_type == 'QUESTION_MCQ':
                            is_correct = (user_input.strip().upper() == 
                                        current_step.get('answer', '').strip().upper())
                            
                            if is_correct:
                                if enrollment:
                                    xp_to_award = 10 if attempts == 0 else 5
                                    log_activity(
                                        current_user, 
                                        'correct_mcq', 
                                        lesson.guidelet, 
                                        lesson, 
                                        xp_earned=xp_to_award
                                    )
                                    response_data['xp_earned'] = xp_to_award
                                
                                next_step_index = step_index + 1

                                if next_step_index >= len(lesson_steps):
                                    task_description = "The student correctly answered the final question. Congratulate them and conclude the chapter enthusiastically."
                                    state_description = "The student has completed the lesson."
                                else:
                                    next_step = lesson_steps[next_step_index]
                                    next_step_type = next_step.get('type')
                                    
                                    intro_content = ""
                                    if next_step_type == 'CONTENT':
                                        intro_content = _replace_media_tags_for_prompt(
                                            next_step.get('text', 'the next topic.')
                                        )
                                    elif next_step_type in ['QUESTION_MCQ', 'QUESTION_SA']:
                                        intro_content = f"the next question: '{next_step.get('question', 'the next question.')}'"
                                    elif next_step_type == 'MEDIA':
                                        intro_content = f"a {next_step.get('media_type', 'media element')} with the description: '{next_step.get('alt_text', 'the next topic.')}'"

                                    task_description = f"The student just correctly answered a question. First, congratulate them (e.g., 'That's right!', 'Excellent!'). Then, smoothly transition to introduce the next part of the lesson. The content to introduce is:\n---\n{intro_content}\n---"
                                    state_description = "The student answered correctly and is ready for the next step."

                                    if next_step_type in ['QUESTION_MCQ', 'QUESTION_SA']:
                                        response_data['question'] = next_step
                                    else:
                                        if next_step_type == 'MEDIA':
                                            response_data['media_url'] = next_step.get('media_url')
                                            response_data['media_type'] = next_step.get('media_type')
                                        next_step_index += 1
                            
                            # --- THIS IS THE FIX FOR INCORRECT MCQ ANSWERS ---
                            else:
                                question_text = current_step.get('question', '')
                                simple_prompt = f"""[TUTOR PERSONA]
{persona}

[YOUR TASK]
The student provided an incorrect answer to the following multiple-choice question: "{question_text}"
Your task is to respond in an encouraging way (e.g., "Not quite," or "That's a good try, but..."). Then, **re-ask the exact same question** to give them another chance. Give some hints.
"""
                                model_response_text = get_tutor_response(simple_prompt)
                                response_data['tutor_text'] = model_response_text
                                response_data['question'] = current_step
                                chat_log.append({
                                    "sender": "tutor", 
                                    "type": "text", 
                                    "content": model_response_text
                                })
                                
                                if enrollment:
                                    history_record.history_json = json.dumps(chat_log)
                                    db.session.commit()
                                
                                return jsonify(response_data)
                            # --- END OF FIX ---

                        elif step_type == 'QUESTION_SA':
                            analysis_prompt = SA_ANALYSIS_PROMPT.format(
                                question=current_step.get('question'),
                                keywords=current_step.get('keywords'),
                                answer=user_input
                            )
                            
                            # 2. Get the AI's evaluation
                            evaluation_response_text = get_tutor_response(analysis_prompt)
                            try:
                                # 3. Parse the JSON response from the AI
                                evaluation_data = json.loads(evaluation_response_text.strip().replace("```json", "").replace("```", "").strip())
                                is_correct = evaluation_data.get('is_correct', False)
                                feedback_from_ai = evaluation_data.get('feedback', "Let's try that again.")
                            except (json.JSONDecodeError, AttributeError):
                                # Fallback if the AI doesn't return valid JSON
                                is_correct = False
                                feedback_from_ai = "I had a little trouble checking your answer. Let's try rephrasing."

                            if is_correct:
                                if enrollment:
                                    xp_to_award = 50
                                    award_xp(current_user, xp_to_award)
                                    log_activity(
                                        current_user, 
                                        'correct_sa', 
                                        lesson.guidelet, 
                                        lesson, 
                                        xp_earned=xp_to_award
                                    )
                                    response_data['xp_earned'] = xp_to_award
                                
                                if current_step.get('reason'):
                                    explanation_prompt = SA_CORRECT_WITH_REASON_PROMPT.format(
                                        question=current_step.get('question'),
                                        reason=current_step.get('reason')
                                    )
                                    explanation_text = get_tutor_response(explanation_prompt)
                                    model_response_text = f"That's absolutely right! Great job.\n\n{explanation_text}"
                                else:
                                    model_response_text = get_tutor_response(
                                        "The user's short answer was correct. Provide a short, encouraging confirmation (e.g., 'Exactly!', 'You've got it!')."
                                    )
                                
                                next_step_index = step_index + 1
                            
                            # --- THIS IS THE FIX FOR INCORRECT SA ANSWERS ---
                            else:
                                
                                model_response_text = feedback_from_ai
                                response_data['question'] = current_step
                                next_step_index = step_index  # Stay on the same step
                            # --- END OF FIX ---
                            
                            response_data['tutor_text'] = model_response_text
                            chat_log.append({
                                "sender": "tutor", 
                                "type": "text", 
                                "content": model_response_text
                            })
                            
                            if enrollment:
                                history_record.current_step_index = next_step_index
                                history_record.history_json = json.dumps(chat_log)
                            else:
                                session[f'preview_chat_{lesson_id}'] = {
                                    'step_index': next_step_index, 
                                    'chunk_index': 0
                                }
                                session.modified = True
                            db.session.commit()
                            return jsonify(response_data)

                    else:
                        question_text = current_step.get('question', '')
                        state_description = "You have just taught some content and will now ask a question to check for understanding."
                        task_description = f"Introduce the following question in an engaging way, according to your persona: '{question_text}'"
                        response_data['question'] = current_step
                        response_data['step_index'] = step_index
                        next_step_index = step_index
                        next_chunk_index = 0
                else:
                    next_step_index = step_index + 1
                    next_chunk_index = 0

    processed_task_description = _replace_media_tags_for_prompt(task_description)
    final_task_description = f"""{processed_task_description}

IMPORTANT: You MUST NOT output raw script tags like [AUDIO: ...] or [IMAGE: ...] in your response. The system is responsible for displaying the media files. Focus only on providing a natural, conversational response based on the task. Use markdown for formatting, especially bolding key terms with double asterisks (e.g., **this is important**).

**CRITICAL RULE: Your response must focus *only* on explaining the content. DO NOT end your response with conversational questions like "Any questions so far?", "Ready to continue?", or "Does that make sense?". The user will click a "Continue" button when they are ready to proceed. Your task is to deliver the information and then stop.**"""

    outline_str = "\n".join([f"- {item}" for item in lesson_outline])
    current_stage = ""
    if step_index < len(lesson_steps):
        current_stage = lesson_steps[step_index].get('stage', '')

    previously_covered_content = []
    if step_index > 0:
        consolidated_steps = []
        i = 0
        while i < step_index:
            step = lesson_steps[i]
            if step.get('type') == 'CONTENT':
                current_stage_name = step.get('stage')
                content_bundle = [step.get('text', '')]
                j = i + 1
                while (j < step_index and 
                       lesson_steps[j].get('type') == 'CONTENT' and 
                       lesson_steps[j].get('stage') == current_stage_name):
                    content_bundle.append(lesson_steps[j].get('text', ''))
                    j += 1
                consolidated_steps.append({
                    'type': 'CONTENT_BUNDLE',
                    'stage': current_stage_name,
                    'content': "\n\n".join(content_bundle)
                })
                i = j
            else:
                consolidated_steps.append(step)
                i += 1
        
        for prev_step in consolidated_steps:
            prev_step_type = prev_step.get('type')
            stage = prev_step.get('stage', '')
            content = ""
            
            if prev_step_type == 'CONTENT_BUNDLE':
                content = prev_step.get('content', '')
            elif prev_step_type == 'MEDIA':
                content = f"[A {prev_step.get('media_type', 'media element')} was shown with the description: {prev_step.get('alt_text', 'No description')}]"
            elif prev_step_type in ['QUESTION_MCQ', 'QUESTION_SA']:
                content = f"[A question was asked: {prev_step.get('question', '')}]"
            
            if (not previously_covered_content or 
                not previously_covered_content[-1].startswith(f"Stage: {stage}")):
                previously_covered_content.append(f"Stage: {stage}\n---\n{content}")
            elif content:
                previously_covered_content.append(content)

    previously_covered_content_str = "\n\n".join(previously_covered_content)
    processed_history_str = _replace_media_tags_for_prompt(previously_covered_content_str)

    if next_step_index < len(lesson_steps):
        new_stage_name = lesson_steps[next_step_index].get('stage', '')
        for i, stage_obj in enumerate(lesson_outline):
            if stage_obj.get('stage') == new_stage_name:
                response_data['new_stage_index'] = i
                break

    full_prompt = f"""[TUTOR PERSONA]
{persona}

[FORMATTING RULES]
Use markdown for formatting, especially bolding key terms with double asterisks (e.g., **this is important**).
**Use double newlines to create separate paragraphs.** This is essential for line breaks.
If you need to include a code block, you MUST wrap it in triple backticks. You can specify the language for highlighting. Example:
```python
print("Hello, World!")
```
You MUST NOT output raw script tags like [AUDIO: ...] or [IMAGE: ...]. The system handles displaying media.

[CHAPTER OUTLINE]
{outline_str}

[CURRENT STAGE]
{current_stage}

[PREVIOUSLY COVERED CONTENT]
{processed_history_str if previously_covered_content else 'This is the first step of the lesson.'}

[CURRENT STATE]
{state_description}

[YOUR TASK]
{final_task_description}
"""

    model_response_text = get_tutor_response(full_prompt)

    if model_response_text:
        response_data['tutor_text'] = model_response_text
        chat_log.append({
            "sender": "tutor", 
            "type": "text", 
            "content": model_response_text
        })
        
        if response_data.get('media_url'):
            chat_log.append({
                "sender": "tutor",
                "type": response_data['media_type'],
                "url": response_data['media_url'],
                "alt": current_step.get('alt_text')
            })

    if response_data.get('tutor_text'):
        text_to_check = response_data['tutor_text']
        match = re.search(r'\[(IMAGE|AUDIO|VIDEO):.*?id="(.*?)".*?\]', text_to_check)
        
        if match and not response_data.get('media_url'):
            full_tag = match.group(0)
            tag_type = match.group(1).lower()
            media_id = match.group(2)
            
            media_step_data = next((
                step for step in lesson_steps 
                if step.get('id') == media_id
            ), None)
            
            if media_step_data:
                response_data['media_url'] = media_step_data.get('media_url')
                response_data['media_type'] = media_step_data.get('media_type', tag_type)
                
                response_data['tutor_text'] = text_to_check.replace(full_tag, '').strip()

                if chat_log and chat_log[-1]['content'] == text_to_check:
                    chat_log[-1]['content'] = response_data['tutor_text']

    if enrollment:
        history_record.current_step_index = next_step_index
        history_record.current_chunk_index = next_chunk_index
        history_record.history_json = json.dumps(chat_log)
    else:
        preview_session_key = f'preview_chat_{lesson_id}'
        session[preview_session_key] = {
            'step_index': next_step_index, 
            'chunk_index': 0
        }
        session.modified = True

    db.session.commit()
    return jsonify(response_data)
@app.route('/chat/delete_last_turn', methods=['POST'])
@login_required
def delete_last_turn():
    lesson_id = request.json.get('lesson_id')
    lesson = Lesson.query.get_or_404(lesson_id)
    enrollment = Enrollment.query.filter_by(user_id=current_user.id, guidelet_id=lesson.guidelet_id).first()
    if enrollment:
        history_record = ChatHistory.query.filter_by(enrollment_id=enrollment.id, lesson_id=lesson.id).first()
        if history_record:
            if history_record.current_chunk_index > 0:
                history_record.current_chunk_index -= 1
            elif history_record.current_step_index > 0:
                history_record.current_step_index -= 1
                # To be safe, find the number of chunks in the previous step
                # This is a complex operation, for now, a simple step back is sufficient.
                history_record.current_chunk_index = 0
            db.session.commit()
            return jsonify({'success': True})
    return jsonify({'success': False, 'message': 'Could not delete turn.'})

@app.route('/play/game/<string:game_id>')
@login_required # Ensures only logged-in users can play games
def play_game(game_id):
    game = InteractiveGame.query.get_or_404(game_id)
    return render_template('play_game.html', game=game)




@app.route('/creator/game-studio')
@login_required
def game_studio():
    games = InteractiveGame.query.filter_by(user_id=current_user.id).order_by(InteractiveGame.created_at.desc()).all()
    return render_template('game_studio.html', games=games)

@app.route('/creator/game/create', methods=['GET', 'POST'])
@login_required
def create_game():
    if request.method == 'POST':
        title = request.form.get('title')
        if not title:
            flash('A game title is required.', 'danger')
            return redirect(request.url)

        new_game = InteractiveGame(
            title=title,
            user_id=current_user.id,
            html_content="<!-- Your HTML structure here -->\n<div id=\"game-container\">\n  <h1>My Game</h1>\n</div>",
            css_content="/* Your CSS styles here */\n#game-container {\n  color: #333;\n}",
            js_content="// Your JavaScript logic here\n// When the game is finished, call:\n// window.parent.postMessage('game_complete', '*');"
        )
        db.session.add(new_game)
        db.session.commit()
        flash(f'Game "{title}" created! Now add its code.', 'success')
        return redirect(url_for('edit_game', game_id=new_game.id))
    
    return render_template('create_game.html')


@app.route('/creator/game/edit/<string:game_id>', methods=['GET', 'POST'])
@login_required
def edit_game(game_id):
    game = InteractiveGame.query.get_or_404(game_id)
    if game.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    if request.method == 'POST':
        game.title = request.form['title']
        game.html_content = request.form['html_content']
        game.css_content = request.form['css_content']
        game.js_content = request.form['js_content']
        db.session.commit()
        flash(f'Game "{game.title}" updated successfully!', 'success')
        return redirect(url_for('game_studio'))

    return render_template('edit_game.html', game=game)

@app.route('/creator/game/delete/<string:game_id>', methods=['POST'])
@login_required
def delete_game(game_id):
    game = InteractiveGame.query.get_or_404(game_id)
    if game.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    db.session.delete(game)
    db.session.commit()
    flash(f'Game "{game.title}" has been deleted.', 'success')
    return redirect(url_for('game_studio'))

@app.route('/api/creator/games')
@login_required
def get_creator_games():
    games = InteractiveGame.query.filter_by(user_id=current_user.id).order_by(InteractiveGame.title).all()
    games_data = [{'id': game.id, 'title': game.title} for game in games]
    return jsonify(games_data)

@app.route('/chat/reset', methods=['POST'])
@login_required
def reset_chat():
    """
    Resets the chat history and persona for a given lesson.
    """
    data = request.json
    lesson_id = data.get('lesson_id')
    if not lesson_id:
        return jsonify({'success': False, 'message': 'Lesson ID is required.'}), 400

    lesson = Lesson.query.get_or_404(lesson_id)
    
    # Clear the persona from the main chat session
    session_key = f'chat_session_{lesson_id}'
    if session_key in session:
        session.pop(session_key, None)

    # Check if the user is enrolled in the guidelet
    enrollment = Enrollment.query.filter_by(
        user_id=current_user.id, 
        guidelet_id=lesson.guidelet_id
    ).first()

    if enrollment:
        # Enrolled user: find their specific chat history for this lesson
        history_record = ChatHistory.query.filter_by(
            enrollment_id=enrollment.id, 
            lesson_id=lesson.id
        ).first()
        if history_record:
            history_record.history_json = '[]'
            history_record.current_step_index = 0
            history_record.current_chunk_index = 0
            db.session.commit()
    else:
        # Preview mode user (creator or admin): clear the preview session data
        is_preview_user = (current_user.id == lesson.guidelet.user_id or current_user.is_admin)
        if is_preview_user:
            preview_session_key = f'preview_chat_{lesson_id}'
            if preview_session_key in session:
                session.pop(preview_session_key, None)
            
            preview_chat_log_key = f'{preview_session_key}_chat_log'
            if preview_chat_log_key in session:
                session.pop(preview_chat_log_key, None)
        else:
            # User is not enrolled and not a previewer, forbidden.
            return jsonify({'success': False, 'message': 'Not authorized to reset.'}), 403

    return jsonify({'success': True})


@app.route('/api/notes', methods=['POST'])
@login_required
def create_note():
    data = request.json
    lesson_id = data.get('lesson_id')
    saved_content = data.get('saved_content')
    user_comment = data.get('user_comment')
    message_index = data.get('message_index')

    if not all([lesson_id, saved_content, message_index is not None]):
        return jsonify({'success': False, 'message': 'Missing required data.'}), 400

    lesson = Lesson.query.get_or_404(lesson_id)
    
    # Security check: ensure user is enrolled in the guidelet
    enrollment = Enrollment.query.filter_by(user_id=current_user.id, guidelet_id=lesson.guidelet_id).first()
    if not enrollment:
        return jsonify({'success': False, 'message': 'Not authorized.'}), 403

    new_note = Note(
        user_id=current_user.id,
        guidelet_id=lesson.guidelet_id,
        lesson_id=lesson.id,
        saved_content=saved_content,
        user_comment=user_comment,
        message_index=message_index
    )
    db.session.add(new_note)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Note saved!'})

@app.route('/api/notes', methods=['GET'])
@login_required
def get_notes():
    notes_query = Note.query.filter_by(user_id=current_user.id).order_by(Note.created_at.asc()).all()
    
    # Group notes by guidelet for the UI
    notes_by_guidelet = {}
    for note in notes_query:
        if note.guidelet_id not in notes_by_guidelet:
            notes_by_guidelet[note.guidelet_id] = {
                'guidelet_title': note.guidelet.title,
                'notes': []
            }
        
        notes_by_guidelet[note.guidelet_id]['notes'].append({
            'id': note.id,
            'saved_content': note.saved_content,
            'user_comment': note.user_comment or '',
            'lesson_id': note.lesson_id,
            'guidelet_id': note.guidelet_id,
            'chapter_number': note.lesson.chapter_number,
            'message_index': note.message_index
        })

    return jsonify(notes_by_guidelet)

@app.route('/api/notes/<int:note_id>', methods=['PUT'])
@login_required
def update_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Not authorized.'}), 403

    data = request.json
    note.user_comment = data.get('user_comment', note.user_comment)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Note updated.'})
@app.route('/notes')
@login_required
def notes_page():
    return render_template('notes.html')

@app.route('/api/notes/<int:note_id>', methods=['DELETE'])
@login_required
def delete_note(note_id):
    note = Note.query.get_or_404(note_id)
    if note.user_id != current_user.id:
        return jsonify({'success': False, 'message': 'Not authorized.'}), 403

    db.session.delete(note)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Note deleted.'})


@app.route('/dashboard')
@login_required
def dashboard():
    if not current_user.username:
        return redirect(url_for('claim_username'))

    enrollments = Enrollment.query.filter_by(user_id=current_user.id).join(Guidelet).order_by(Guidelet.title).all()
    
    # Get IDs of users the current user is following for the activity feed
    followed_user_ids = [user.id for user in current_user.following]
    activities = Activity.query.filter(Activity.user_id.in_(followed_user_ids)).order_by(Activity.timestamp.desc()).limit(20).all()

    # --- NEW: Fetch notifications for the Learner Circle tab ---
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.timestamp.desc()).all()
    
    # Mark all notifications as read when the dashboard is visited
    for notification in notifications:
        notification.is_read = True
    db.session.commit()

    # --- Contextual Weekly Leaderboard Logic ---
    leaderboard = []
    enrolled_guidelet_ids = [e.guidelet_id for e in enrollments]

    if enrolled_guidelet_ids:
        # Find all user IDs enrolled in the same guidelets
        competitor_user_ids_query = db.session.query(Enrollment.user_id).filter(
            Enrollment.guidelet_id.in_(enrolled_guidelet_ids)
        ).distinct()
        
        competitor_user_ids = [id_tuple[0] for id_tuple in competitor_user_ids_query.all()]

        # Fetch the User objects for the leaderboard
        leaderboard_users = User.query.filter(User.id.in_(competitor_user_ids)).all()
        
        seven_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
        
        for user in leaderboard_users:
            xp_this_week = db.session.query(db.func.sum(Activity.xp_earned)).filter(
                Activity.user_id == user.id,
                Activity.timestamp >= seven_days_ago
            ).scalar() or 0
            
            if xp_this_week > 0:
                leaderboard.append({'user': user, 'xp': xp_this_week})
                
        # Sort leaderboard by XP
        leaderboard.sort(key=lambda x: x['xp'], reverse=True)
    
    return render_template('dashboard.html', 
                           enrollments=enrollments, 
                           activities=activities, 
                           leaderboard=leaderboard[:10],
                           notifications=notifications)

# In /app.py

@app.route('/claim_username', methods=['GET', 'POST'])
@login_required
def claim_username():
    # This check prevents already-registered users from accessing this page.
    if current_user.username:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        avatar_url = request.form.get('avatar_url') # <-- Get the selected avatar

        if not username:
            flash('Please enter a username.', 'warning')
            return redirect(url_for('claim_username'))

        # Check if username is already taken
        if User.query.filter_by(username=username).first():
            flash('That username is already taken. Please choose another.', 'warning')
            return redirect(url_for('claim_username'))
        
        current_user.username = username
        
        # --- NEW: Save the selected avatar URL ---
        # If the user didn't select one, it will default to None, 
        # which will then use the default avatar set on the User model.
        if avatar_url:
            current_user.avatar_url = avatar_url
        # --- END NEW ---

        db.session.commit()
        flash(f'Welcome, {username}!', 'success')
        
        next_page = session.pop('next_after_claim', None)
        return redirect(next_page or url_for('dashboard'))
        
    # --- NEW: Fetch avatars for the GET request ---
    # This logic fetches the avatars to display on the page.
    avatar_path = os.path.join(app.static_folder, 'images/main_set')
    avatars = [f'/static/images/main_set/{f}' for f in os.listdir(avatar_path) if f.endswith(('.png', '.jpg', '.jpeg', '.gif'))]
    # --- END NEW ---
        
    return render_template('claim_username.html', avatars=avatars)

@app.route('/creator')
@login_required
def creator_dashboard():
    from sqlalchemy.orm import subqueryload

    # Subquery to get total watch time for each guidelet
    watch_time_subquery = db.session.query(
        DailyWatchTime.guidelet_id,
        func.sum(DailyWatchTime.seconds_watched).label('total_watch_time')
    ).group_by(DailyWatchTime.guidelet_id).subquery()

    # Eagerly load relationships to avoid N+1 queries
    created_guidelets_query = db.session.query(
        Guidelet,
        func.coalesce(watch_time_subquery.c.total_watch_time, 0).label('total_watch_time')
    ).outerjoin(
        watch_time_subquery, Guidelet.id == watch_time_subquery.c.guidelet_id
    ).options(
        subqueryload(Guidelet.enrollees),
        subqueryload(Guidelet.reviews)
    ).filter(
        Guidelet.user_id == current_user.id
    ).order_by(Guidelet.title)

    created_guidelets_with_stats = created_guidelets_query.all()
    
    # Now that data is loaded, calculations are safe and efficient
    total_enrollments = sum(len(g.enrollees) for g, _ in created_guidelets_with_stats)
    
    all_reviews = []
    for g, _ in created_guidelets_with_stats:
        all_reviews.extend(g.reviews)
        
    total_reviews = len(all_reviews)
    total_rating_points = sum(r.rating for r in all_reviews)
    
    average_rating = (total_rating_points / total_reviews) if total_reviews > 0 else 0
    
    return render_template('creator_dashboard.html', 
                           created_guidelets_with_stats=created_guidelets_with_stats,
                           total_enrollments=total_enrollments,
                           average_rating=average_rating,
                           total_reviews=total_reviews)

# --- FIX: ADD THE MISSING ROUTE ---
@app.route('/guidelet/create', methods=['POST'])
@login_required
def create_guidelet():
    title = request.form.get('title')
    if not title:
        flash('A title is required to create a guidelet.', 'warning')
        return redirect(url_for('creator_dashboard'))
    new_guidelet = Guidelet(title=title, user_id=current_user.id)
    generate_and_save_embedding(new_guidelet)
    db.session.add(new_guidelet)
    db.session.commit()
    flash('Guidelet created! You can now manage it.', 'success')
    return redirect(url_for('manage_guidelet', guidelet_id=new_guidelet.id))

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        current_user.username = request.form.get('username')
        current_user.bio = request.form.get('bio')
        current_user.avatar_url = request.form.get('avatar_url')
        
        link_names = request.form.getlist('link_name')
        link_urls = request.form.getlist('link_url')
        
        links = {}
        for name, url in zip(link_names, link_urls):
            if name and url:
                links[name] = url
        current_user.links = links
        
        db.session.commit()
        flash('Your profile has been updated.', 'success')
        return redirect(url_for('edit_profile'))
        
    avatar_path = os.path.join(app.static_folder, 'images/main_set')
    
    # 2. Build the list of URLs for the template, making sure they point to the new folder.
    avatars = [f'/static/images/main_set/{f}' for f in os.listdir(avatar_path) if f.endswith(('.png', '.jpg', '.jpeg', '.gif'))]
    
    return render_template('edit_profile.html', avatars=avatars)

@app.route('/profile/delete', methods=['POST'])
@login_required
def delete_account():
    user = User.query.get(current_user.id)
    if user:
        logout_user()
        db.session.delete(user)
        db.session.commit()
        flash('Your account and all associated data have been permanently deleted.', 'success')
    return redirect(url_for('index'))

@app.route('/profile/export')
@login_required
def export_data():
    user = User.query.get(current_user.id)
    
    guidelets_data = []
    for guidelet in user.guidelets:
        lessons_data = []
        for lesson in guidelet.lessons:
            lessons_data.append({
                'title': lesson.title,
                'chapter_number': lesson.chapter_number,
                'raw_script': lesson.raw_script,
            })
        guidelets_data.append({
            'title': guidelet.title,
            'description': guidelet.description,
            'lessons': lessons_data
        })

    reviews_data = []
    for review in user.reviews:
        reviews_data.append({
            'guidelet': review.guidelet.title,
            'rating': review.rating,
            'comment': review.comment,
            'created_at': review.created_at.isoformat()
        })

    user_data = {
        'username': user.username,
        'email': user.email,
        'bio': user.bio,
        'xp': user.xp,
        'guidelets_created': guidelets_data,
        'reviews_written': reviews_data
    }

    return jsonify(user_data)

from sqlalchemy import func, cast, Date

from sqlalchemy import func, cast, Date

from sqlalchemy import func, cast, Date

# In app.py

# In app.py

# In app.py

@app.route('/user/<string:username>')
def user_profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    
    today = datetime.datetime.utcnow().date()
    if user.last_xp_reset_date and (user.last_xp_reset_date.year < today.year or user.last_xp_reset_date.month < today.month):
        user.monthly_xp = 0
        user.tree_stage = 0
        user.last_xp_reset_date = today
        db.session.commit()

    # --- START: UPDATED IMAGE URLS ---
    # The first three URLs are now your correct ones.
    # TODO: Replace the placeholder URLs for stages 3-10 once you upload them.
    tree_image_urls = [
        "https://res.cloudinary.com/dltx0ursv/image/upload/v1755071954/game_assets/0.png",   # Stage 0 (Correct)
        "https://res.cloudinary.com/dltx0ursv/image/upload/v1755071997/game_assets/1.png",   # Stage 1 (Correct)
        "https://res.cloudinary.com/dltx0ursv/image/upload/v1755072036/game_assets/2.png",   # Stage 2 (Correct)
        "https://res.cloudinary.com/dltx0ursv/image/upload/v1755072036/game_assets/3.png",   # Stage 3 (Placeholder)
        "https://res.cloudinary.com/dltx0ursv/image/upload/v1755072036/game_assets/4.png",   # Stage 4 (Placeholder)
        "https://res.cloudinary.com/dltx0ursv/image/upload/v1755072036/game_assets/5.png",   # Stage 5 (Placeholder)
        "https://res.cloudinary.com/dltx0ursv/image/upload/v1755072036/game_assets/6.png",   # Stage 6 (Placeholder)
        "https://res.cloudinary.com/dltx0ursv/image/upload/v1755072036/game_assets/7.png",   # Stage 7 (Placeholder)
        "https://res.cloudinary.com/dltx0ursv/image/upload/v1755072036/game_assets/8.png",   # Stage 8 (Placeholder)
        "https://res.cloudinary.com/dltx0ursv/image/upload/v1755072036/game_assets/9.png",   # Stage 9 (Placeholder)
        "https://res.cloudinary.com/dltx0ursv/image/upload/v1755072036/game_assets/10.png"  # Stage 10 (Placeholder)
    ]
    # --- END: UPDATED IMAGE URLS ---

    tree_stage = user.tree_stage or 0
    current_tree_image_url = tree_image_urls[tree_stage]

    # History fetching logic...
    past_groves_display_data = []
    month_names = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    saved_groves = user.monthly_groves.order_by(MonthlyGrove.year.desc(), MonthlyGrove.month.desc()).all()
    groves_dict = {(g.year, g.month): g for g in saved_groves}
    seen_months = set() 

    for i in range(12):
        current_check_date = today - datetime.timedelta(days=30 * i)
        year, month = current_check_date.year, current_check_date.month
        if (year, month) in seen_months:
            continue
        seen_months.add((year, month))

        grove_data = groves_dict.get((year, month))
        if grove_data:
            past_groves_display_data.append({ "display_date": f"{month_names[month]} {year}", "stage": grove_data.final_tree_stage, "xp": grove_data.final_xp, "message": None })
        else:
            funny_messages = ["The soil was resting this month.", "Even the best gardeners take a break.", "This grove was fallow for the season.", "A month of quiet contemplation.", "The seeds of knowledge were dormant here."]
            past_groves_display_data.append({ "display_date": f"{month_names[month]} {year}", "stage": 0, "xp": 0, "message": random.choice(funny_messages) })

    # Existing logic for guidelets, enrollments, and XP chart...
    created_guidelets = Guidelet.query.filter_by(user_id=user.id, status='published').order_by(Guidelet.title).all()
    enrollments = Enrollment.query.filter_by(user_id=user.id).join(Guidelet).filter(Guidelet.status == 'published').order_by(Guidelet.title).all()
    
    ist = pytz.timezone('Asia/Kolkata')
    today_ist = datetime.datetime.now(ist).date()
    start_date = today_ist - datetime.timedelta(days=30)
    start_timestamp_utc = datetime.datetime.combine(start_date, datetime.time.min) - datetime.timedelta(days=1)
    activities_in_window = db.session.query(Activity.timestamp, Activity.xp_earned).filter(Activity.user_id == user.id, Activity.timestamp >= start_timestamp_utc).all()
    daily_xp_map = {}
    for activity_ts, xp_earned in activities_in_window:
        ist_dt = activity_ts.replace(tzinfo=pytz.utc).astimezone(ist)
        ist_date = ist_dt.date()
        if ist_date >= start_date:
            daily_xp_map[ist_date] = daily_xp_map.get(ist_date, 0) + (xp_earned or 0)
    chart_labels = []
    chart_values = []
    for i in range(31):
        current_date = start_date + datetime.timedelta(days=i)
        daily_gain = daily_xp_map.get(current_date, 0)
        chart_labels.append(current_date.strftime('%b %d'))
        chart_values.append(daily_gain)



     # --- START: NEW PROGRESS INDICATOR LOGIC ---

    # Define thresholds including stage 0. The index of this list now matches the stage number.
    xp_thresholds_full = [0, 100, 250, 500, 800, 1200, 1700, 2300, 3000, 4000, 5000]
    
    progress_data = {
        "xp_needed": 0,
        "percentage": 0,
        "is_max_stage": False
    }

    if tree_stage >= 10:
        # User has reached the maximum stage for the month
        progress_data["is_max_stage"] = True
        progress_data["percentage"] = 100
    else:
        # Calculate progress for the current stage
        xp_for_current_stage_start = xp_thresholds_full[tree_stage]
        xp_for_next_stage_start = xp_thresholds_full[tree_stage + 1]
        
        # How much XP is needed to complete the current stage's progress bar
        total_xp_in_stage = xp_for_next_stage_start - xp_for_current_stage_start
        
        # How much XP the user has earned *within* this current stage
        xp_earned_in_stage = (user.monthly_xp or 0) - xp_for_current_stage_start
        
        # How many more XP points are needed to level up
        progress_data["xp_needed"] = xp_for_next_stage_start - (user.monthly_xp or 0)
        
        # Calculate the percentage for the progress bar's width
        if total_xp_in_stage > 0:
            progress_data["percentage"] = min(100, (xp_earned_in_stage / total_xp_in_stage) * 100)

    return render_template(
        'creator_profile.html',
        creator=user,
        created_guidelets=created_guidelets,
        enrollments=enrollments,
        chart_labels=json.dumps(chart_labels),
        chart_values=json.dumps(chart_values),
        tree_image_url=current_tree_image_url,
        past_groves=past_groves_display_data,
        tree_image_urls=tree_image_urls,
        progress_data=progress_data
    )

from sqlalchemy import func
from thefuzz import process, fuzz

@app.route('/find_learners')
@login_required
def find_learners():
    query = request.args.get('q')
    
    # Subquery to count completed guidelets for each user
    completed_guidelets_subquery = db.session.query(
        Enrollment.user_id,
        func.count(Enrollment.id).label('completed_count')
    ).filter(Enrollment.completed_at.isnot(None)).group_by(Enrollment.user_id).subquery()

    # Base query to get users and their completion stats
    base_query = db.session.query(
    User,
    func.coalesce(completed_guidelets_subquery.c.completed_count, 0)
    ).outerjoin(
    completed_guidelets_subquery, User.id == completed_guidelets_subquery.c.user_id
    ).filter(User.username.isnot(None))

    if query:
        all_users_with_stats = base_query.all()
        
        # Use thefuzz to score and sort users
        users_with_scores = []
        for user, completed_count in all_users_with_stats:
            if user.username: # Ensure username is not None
                score = fuzz.partial_ratio(query.lower(), user.username.lower())
                if score > 60: # Threshold to filter out very dissimilar names
                    users_with_scores.append(((user, completed_count), score))
        
        # Sort by score, descending
        users_with_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Extract the sorted (user, completed_count) tuples
        users_with_stats = [item[0] for item in users_with_scores]
    else:
        # If no query, just get all users ordered by username
        users_with_stats = base_query.order_by(User.username).all()

    return render_template('find_learners.html', users_with_stats=users_with_stats, search_query=query)

@app.route('/follow/<int:user_id>', methods=['POST'])
@login_required
def follow(user_id):
    user_to_follow = User.query.get_or_404(user_id)
    if user_to_follow == current_user:
        flash("You cannot follow yourself.", "warning")
        return redirect(url_for('find_learners'))
    current_user.follow(user_to_follow)
    
    # Create a notification for the user who was followed
    notification = Notification(
        user_id=user_to_follow.id,
        message=f"{current_user.username} started following you."
    )
    db.session.add(notification)
    
    db.session.commit()
    flash(f"You are now following {user_to_follow.username}.", "success")
    return redirect(request.referrer or url_for('find_learners'))

@app.route('/unfollow/<int:user_id>', methods=['POST'])
@login_required
def unfollow(user_id):
    user_to_unfollow = User.query.get_or_404(user_id)
    if user_to_unfollow == current_user:
        flash("You cannot unfollow yourself.", "warning")
        return redirect(url_for('find_learners'))
    current_user.unfollow(user_to_unfollow)
    db.session.commit()
    flash(f"You have unfollowed {user_to_unfollow.username}.", "info")
    return redirect(request.referrer or url_for('find_learners'))



@app.route('/guidelet/<string:guidelet_id>/manage')
@login_required
def manage_guidelet(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    if guidelet.creator.id != current_user.id and not current_user.is_admin:
        abort(403)

    # --- FINALIZED: Query for Daily Watch Time Analytics (Last 30 Days) ---
    ist = pytz.timezone('Asia/Kolkata')
    today = datetime.datetime.now(ist).date()
    thirty_days_ago = today - datetime.timedelta(days=29)

    daily_data = db.session.query(
        DailyWatchTime.date,
        func.sum(DailyWatchTime.seconds_watched).label('total_seconds')
    ).filter(
        DailyWatchTime.guidelet_id == guidelet_id,
        DailyWatchTime.date >= thirty_days_ago
    ).group_by(
        DailyWatchTime.date
    ).all()

    watch_time_map = {item.date: item.total_seconds for item in daily_data}

    chart_labels = []
    chart_values = []
    background_colors = []
    month_labels = []
    last_month = None
    
    for i in range(30):
        current_date = thirty_days_ago + datetime.timedelta(days=i)
        
        chart_labels.append(current_date.strftime('%b %d'))
        
        if current_date.weekday() >= 5:  # Saturday or Sunday
            background_colors.append('rgba(54, 162, 235, 0.2)')
        else:
            background_colors.append('rgba(54, 162, 235, 0.5)')

        current_month = current_date.strftime('%b')
        if current_month != last_month:
            if last_month is not None:
                month_labels.append({
                    'position': i,
                    'label': current_month
                })
            last_month = current_month
        
        seconds_for_day = watch_time_map.get(current_date, 0)
        chart_values.append(seconds_for_day)
    
    date_range_label = f"{thirty_days_ago.strftime('%b %d')} - {today.strftime('%b %d, %Y')}"

    return render_template(
        'manage_guidelet.html',
        guidelet=guidelet,
        chart_labels=chart_labels,
        chart_values=chart_values,
        background_colors=background_colors,
        month_labels=month_labels,
        date_range_label=date_range_label
    )

# --- Routes from here down are mostly unchanged, but included for completeness ---
@app.route('/guidelet/<string:guidelet_id>/add_chapter', methods=['GET'])
@login_required
def add_chapter_page(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    if guidelet.creator.id != current_user.id: abort(403)
    return render_template('create_chapter.html', guidelet=guidelet)

# Located in app.py

@app.route('/guidelet/<string:guidelet_id>/save_chapter', methods=['POST'])
@login_required
def save_chapter(guidelet_id):
    """
    Handles the creation of a new chapter, including media uploads,
    sanitization of editor content, and parsing of the lesson script.
    """
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    if guidelet.creator.id != current_user.id and not current_user.is_admin:
        abort(403)
    
    script = request.form['script']
    title = request.form['title']
    
    # Sanitize the incoming editor_html to remove temporary blob previews before saving
    raw_editor_html = request.form.get('editor_html', script)
    editor_html = _clean_editor_html(raw_editor_html)
    
    if not title or not script.strip():
        flash('Both a title and script content are required.', 'warning')
        return redirect(url_for('add_chapter_page', guidelet_id=guidelet.id))

    # --- Process New Media Uploads ---
    media_ids = request.form.getlist('media_ids')
    uploaded_files = request.files.getlist('media_files')
    
    id_to_file_map = {mid: file for mid, file in zip(media_ids, uploaded_files) if file and file.filename}
    
    id_to_url_map = {}
    for media_id, file in id_to_file_map.items():
        if not allowed_file(file.filename):
            flash(f"Invalid file type: {file.filename}", 'danger')
            return redirect(request.url)
        
        try:
            # Upload the file to Cloudinary
            upload_result = cloudinary.uploader.upload(
                file,
                resource_type='auto',
                folder=f"coursewell_prod/{guidelet.id}"
            )
            secure_url = upload_result.get('secure_url')
            media_type = "image"
            if upload_result.get('resource_type') == 'video':
                media_type = "audio" if upload_result.get('is_audio') else "video"

            # Transform video URLs to be web-playable
            final_url = secure_url
            if media_type == 'video':
                parts = secure_url.split('/upload/')
                final_url = f"{parts[0]}/upload/vc_auto/{parts[1]}"
                base_url, _ = os.path.splitext(final_url)
                final_url = f"{base_url}.mp4"

            # Store the final URL and type to be used by the parser
            id_to_url_map[media_id] = {
                "url": final_url,
                "type": media_type
            }
        except Exception as e:
            flash(f"Error uploading file: {e}", "danger")
            return redirect(request.url)

    # Create a temporary parsed structure with the new media URLs.
    # The _parse_and_save_lesson function will use this as its starting point.
    temp_parsed_data = {'steps': []}
    for media_id, data in id_to_url_map.items():
        temp_parsed_data['steps'].append({
            'type': 'MEDIA',
            'id': media_id,
            'media_url': data['url'],
            'media_type': data['type'],
        })

    # --- Create and Save the Lesson Object ---
    last_chapter = Lesson.query.filter_by(guidelet_id=guidelet_id).order_by(Lesson.chapter_number.desc()).first()
    new_chapter_number = (last_chapter.chapter_number + 1) if last_chapter else 1
    
    new_lesson = Lesson(
        title=title, 
        raw_script=script, 
        editor_html=editor_html, # Save the sanitized HTML
        parsed_json=json.dumps(temp_parsed_data), # Save the temp media URLs
        guidelet_id=guidelet.id, 
        chapter_number=new_chapter_number
    )
    db.session.add(new_lesson)
    
    try:
        # Call the main parsing function which will now generate the final, structured JSON
        _parse_and_save_lesson(new_lesson)
        db.session.commit() # Commit all changes if parsing is successful
        flash('Chapter added and processed successfully!', 'success')
    except Exception as e:
        db.session.rollback() # Rollback all changes if parsing fails
        print(f"ERROR: Failed to save and parse new chapter. Error: {e}")
        flash(f'The chapter was saved, but failed to process correctly: {e}. Please try editing it to fix the issue.', 'danger')

    return redirect(url_for('manage_guidelet', guidelet_id=guidelet.id))

@app.route('/chapter/<string:lesson_id>/edit', methods=['GET'])
@login_required
def edit_chapter_page(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    if lesson.guidelet.creator.id != current_user.id: abort(403)
    
    # --- FIX: Create a map of ID to URL for robust preview rendering ---
    media_map = {}
    if lesson.parsed_json:
        try:
            lesson_data = json.loads(lesson.parsed_json)
            for step in lesson_data.get('steps', []):
                if step.get('type') == 'MEDIA' and step.get('media_url') and step.get('id'):
                    media_map[step.get('id')] = step.get('media_url')
        except (json.JSONDecodeError, AttributeError):
            pass # Ignore errors if JSON is malformed

    return render_template('edit_chapter.html', lesson=lesson, media_map=json.dumps(media_map))

# In app.py

# Located in app.py

@app.route('/chapter/<string:lesson_id>/update', methods=['POST'])
@login_required
def update_chapter(lesson_id):
    """
    Handles the updating of an existing chapter. It includes sanitizing
    editor content, managing new and existing media, and re-parsing the
    entire lesson script to reflect the changes.
    """
    lesson = Lesson.query.get_or_404(lesson_id)
    if lesson.guidelet.creator.id != current_user.id and not current_user.is_admin:
        abort(403)
    
    # Check if the guidelet was published before this edit
    course_was_published = lesson.guidelet.is_published

    # --- Sanitize and Update Basic Lesson Fields ---
    script = request.form['script']
    
    # Sanitize the incoming editor HTML to remove temporary blob previews
    raw_editor_html = request.form.get('editor_html', script)
    editor_html = _clean_editor_html(raw_editor_html)

    lesson.title = request.form['title']
    lesson.raw_script = script
    lesson.editor_html = editor_html # Save the sanitized HTML

    # --- Consolidate Existing and New Media ---

    # 1. Get existing media URLs from the current parsed_json
    existing_media = {}
    if lesson.parsed_json:
        try:
            old_data = json.loads(lesson.parsed_json)
            for step in old_data.get('steps', []):
                if step.get('type') == 'MEDIA' and step.get('id') and step.get('media_url'):
                    existing_media[step.get('id')] = {
                        "url": step['media_url'],
                        "type": step.get('media_type', 'image')
                    }
        except (json.JSONDecodeError, AttributeError):
            print(f"Warning: Could not parse existing JSON for lesson {lesson.id}. It will be overwritten.")

    # 2. Process any newly uploaded files during this edit
    media_ids = request.form.getlist('media_ids')
    uploaded_files = request.files.getlist('media_files')
    
    id_to_file_map = {mid: file for mid, file in zip(media_ids, uploaded_files) if file and file.filename}
    
    for media_id, file in id_to_file_map.items():
        if not allowed_file(file.filename):
            flash(f"Invalid file type: {file.filename}", 'danger')
            return redirect(request.url)
        
        try:
            upload_result = cloudinary.uploader.upload(file, resource_type='auto', folder=f"coursewell_prod/{lesson.guidelet.id}")
            secure_url = upload_result.get('secure_url')
            media_type = "image"
            if upload_result.get('resource_type') == 'video':
                media_type = "audio" if upload_result.get('is_audio') else "video"

            # Transform video URLs for web playback
            final_url = secure_url
            if media_type == 'video':
                parts = secure_url.split('/upload/')
                final_url = f"{parts[0]}/upload/vc_auto/{parts[1]}"
                base_url, _ = os.path.splitext(final_url)
                final_url = f"{base_url}.mp4"

            # Add or overwrite the media in our map
            existing_media[media_id] = {
                "url": final_url,
                "type": media_type
            }
        except Exception as e:
            flash(f"Error uploading new file: {e}", "danger")
            return redirect(request.url)

    # 3. Create a temporary JSON with ALL media data (old and new) for the parser to use
    temp_steps = []
    for media_id, data in existing_media.items():
        temp_steps.append({
            'type': 'MEDIA',
            'id': media_id,
            'media_url': data['url'],
            'media_type': data['type']
        })
    lesson.parsed_json = json.dumps({'steps': temp_steps})
    
    # Invalidate the in-memory RAG cache for this lesson since its content has changed
    if lesson.id in RAG_RETRIEVERS:
        del RAG_RETRIEVERS[lesson.id]

    # --- Re-parse, Finalize, and Commit ---
    try:
        # Re-run the full parsing logic on the updated lesson object
        _parse_and_save_lesson(lesson)
        
        # If the guidelet was live, return it to drafts to require re-review
        if course_was_published:
            lesson.guidelet.status = 'draft'
            lesson.guidelet.is_published = False
            flash('Chapter updated! The guidelet has been returned to draft status and will need to be re-submitted for review.', 'info')
        else:
            flash('Chapter updated and processed successfully!', 'success')
        
        db.session.commit() # Commit all changes
    except Exception as e:
        db.session.rollback()
        print(f"ERROR: Failed to update and re-parse chapter {lesson.id}. Error: {e}")
        flash(f'Failed to update and process the chapter: {e}. Please check your script for errors and try again.', 'danger')

    return redirect(url_for('manage_guidelet', guidelet_id=lesson.guidelet_id))

@app.route('/chapter/<string:lesson_id>/delete', methods=['POST'])
@login_required
def delete_chapter(lesson_id):
    lesson = Lesson.query.get_or_404(lesson_id)
    if lesson.guidelet.creator.id != current_user.id: abort(403)
    guidelet_id = lesson.guidelet.id
    deleted_chapter_number = lesson.chapter_number
    db.session.delete(lesson)
    subsequent_chapters = Lesson.query.filter(Lesson.guidelet_id == guidelet_id, Lesson.chapter_number > deleted_chapter_number).order_by(Lesson.chapter_number).all()
    for chapter in subsequent_chapters: chapter.chapter_number -= 1
    if lesson.id in RAG_RETRIEVERS: del RAG_RETRIEVERS[lesson.id]
    db.session.commit()
    flash('Chapter deleted successfully.', 'success')
    return redirect(url_for('manage_guidelet', guidelet_id=guidelet_id))

@app.route('/guidelet/<string:guidelet_id>/reorder_chapters', methods=['POST'])
@login_required
def reorder_chapters(guidelet_id):
    """Receives the new order of chapter IDs and updates the database."""
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    if guidelet.creator.id != current_user.id and not current_user.is_admin:
        abort(403)

    data = request.get_json()
    ordered_ids = data.get('order')

    if not ordered_ids:
        return jsonify({'success': False, 'message': 'Missing order data'}), 400

    # Create a map of the guidelet's lessons for efficient lookup
    lessons_map = {str(lesson.id): lesson for lesson in guidelet.lessons}

    try:
        # Iterate through the received order and update the chapter_number
        for index, lesson_id in enumerate(ordered_ids):
            if lesson_id in lessons_map:
                lessons_map[lesson_id].chapter_number = index + 1
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        print(f"Error reordering chapters: {e}") # Log the error for debugging
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


@app.route('/guidelet/<string:guidelet_id>/delete', methods=['POST'])
@login_required
def delete_guidelet(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    if guidelet.creator.id != current_user.id: abort(403)
    guidelet_title = guidelet.title
    db.session.delete(guidelet)
    db.session.commit()
    flash(f"Guidelet '{guidelet_title}' has been permanently deleted.", 'success')
    return redirect(url_for('creator_dashboard'))

@app.route('/guidelet/<string:guidelet_id>/submit_review', methods=['POST'])
@login_required
def submit_for_review(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    if guidelet.creator.id != current_user.id: abort(403)
    guidelet.status = 'pending_review'
    guidelet.is_published = False
    db.session.commit()
    flash('Your guidelet has been submitted for review!', 'success')
    return redirect(url_for('manage_guidelet', guidelet_id=guidelet.id))

@app.route('/guidelet/<string:guidelet_id>/unpublish', methods=['POST'])
@login_required
def unpublish_guidelet(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    if guidelet.creator.id != current_user.id and not current_user.is_admin: abort(403)
    guidelet.status = 'draft'
    guidelet.is_published = False
    db.session.commit()
    flash('Guidelet has been unpublished and returned to draft status.', 'info')
    # Redirect back to the same page the action was taken on
    return redirect(request.referrer or url_for('explore'))

from sqlalchemy.orm import joinedload, subqueryload
from sqlalchemy import func
from thefuzz import process, fuzz

@app.route('/explore')
def explore():
    search_query = request.args.get('q', '')
    sort_by = request.args.get('sort', 'newest')
    category = request.args.get('category', 'all')

    guidelets_query = Guidelet.query.options(
        joinedload(Guidelet.creator),
        subqueryload(Guidelet.lessons),
        subqueryload(Guidelet.reviews)
    ).filter(Guidelet.status == 'published')

    guidelets = []

    if search_query:
        try:
            SIMILARITY_THRESHOLD = 0.55
            query_embedding_result = genai.embed_content(
                model='models/text-embedding-004',
                content=search_query,
                task_type="RETRIEVAL_QUERY"
            )
            query_embedding = np.array(query_embedding_result['embedding'])
            all_guidelets_with_embeddings = guidelets_query.filter(Guidelet.search_embedding.isnot(None)).all()
            
            guidelet_scores = []
            for guidelet in all_guidelets_with_embeddings:
                guidelet_embedding = np.array(json.loads(guidelet.search_embedding))
                similarity = np.dot(query_embedding, guidelet_embedding) / (np.linalg.norm(query_embedding) * np.linalg.norm(guidelet_embedding))
                
                if similarity >= SIMILARITY_THRESHOLD:
                    guidelet_scores.append((guidelet, similarity))

            guidelet_scores.sort(key=lambda x: x[1], reverse=True)
            guidelets = [item[0] for item in guidelet_scores]
            sort_by = 'relevance'

            if not guidelets:
                print("AI search returned no relevant results, falling back to keyword search.")
                guidelets = guidelets_query.filter(
                    or_(Guidelet.title.ilike(f'%{search_query}%'), Guidelet.description.ilike(f'%{search_query}%'))
                ).all()

        except Exception as e:
            print(f"AI search failed, falling back to keyword search. Error: {e}")
            guidelets = guidelets_query.filter(
                or_(Guidelet.title.ilike(f'%{search_query}%'), Guidelet.description.ilike(f'%{search_query}%'))
            ).all()
    else:
        # Original logic for when there is no search query
        guidelets = guidelets_query.all()


    # --- UPDATED: AUTOMATIC TOPIC REQUEST FOR ALL USERS ---
    if search_query and not guidelets:
        if current_user.is_authenticated:
            # Logic for logged-in users (uses user_id)
            existing_request = TopicRequest.query.filter(
                func.lower(TopicRequest.topic_title) == search_query.lower(),
                TopicRequest.user_id == current_user.id
            ).first()
            if not existing_request:
                new_request = TopicRequest(
                    topic_title=search_query,
                    details="Automatically requested via search bar (Logged-in User).",
                    user_id=current_user.id
                )
                db.session.add(new_request)
                db.session.commit()
                print(f"Automatically created topic request for '{search_query}' by user {current_user.username}")
        else:
            # Logic for anonymous users (uses session_id)
            # We create a unique ID for the anonymous session if it doesn't exist
            if 'anonymous_user_id' not in session:
                session['anonymous_user_id'] = str(uuid.uuid4())
            
            session_id = session['anonymous_user_id']
            
            existing_request = TopicRequest.query.filter(
                func.lower(TopicRequest.topic_title) == search_query.lower(),
                TopicRequest.session_id == session_id
            ).first()
            
            if not existing_request:
                new_request = TopicRequest(
                    topic_title=search_query,
                    details="Automatically requested via search bar (Anonymous User).",
                    session_id=session_id
                )
                db.session.add(new_request)
                db.session.commit()
                print(f"Automatically created topic request for '{search_query}' by anonymous session {session_id}")
    # --- END OF UPDATED LOGIC ---


    categories_query = db.session.query(Guidelet.category).filter(Guidelet.category.isnot(None)).distinct()
    categories = [c[0] for c in categories_query.all()]
    
    return render_template('explore.html', 
                           guidelets=guidelets, 
                           categories=categories,
                           search_query=search_query,
                           sort_by=sort_by,
                           current_category=category)

@app.route('/guidelet/<string:guidelet_id>')
@login_required
def guidelet_player(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    is_authorized = guidelet.status == 'published' or (current_user.is_authenticated and (current_user.id == guidelet.user_id or current_user.is_enrolled(guidelet) or current_user.is_admin))
    if not is_authorized: abort(404)
    if not guidelet.lessons:
        if current_user.is_authenticated and current_user.id == guidelet.user_id:
            flash('This guidelet has no chapters yet. Add one to enable the preview.', 'info')
            return redirect(url_for('manage_guidelet', guidelet_id=guidelet.id))
        flash("This guidelet has no content yet.", "warning")
        return redirect(url_for('explore'))
    chapter_to_start = 1
    enrollment = Enrollment.query.filter_by(user_id=current_user.id, guidelet_id=guidelet.id).first()
    if enrollment:
        chapter_to_start = enrollment.last_completed_chapter_number + 1
        if chapter_to_start > len(guidelet.lessons): chapter_to_start = len(guidelet.lessons)
    return redirect(url_for('student_chapter_view', guidelet_id=guidelet.id, chapter_number=chapter_to_start))

# In app.py

@app.route('/guidelet/<string:guidelet_id>/<int:chapter_number>')
@login_required
def student_chapter_view(guidelet_id, chapter_number):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    
    is_authorized = (guidelet.status == 'published') or \
                    (current_user.is_authenticated and 
                     (current_user.id == guidelet.user_id or 
                      current_user.is_enrolled(guidelet) or 
                      current_user.is_admin))
                      
    if not is_authorized:
        abort(404)

    lesson = Lesson.query.filter_by(guidelet_id=guidelet.id, chapter_number=chapter_number).first_or_404()

    # Initialize variables to avoid UnboundLocalError
    lesson_data = {}
    lesson_outline = []
    outline_stage_names = []  # This will hold the list of stage names

    try:
        lesson_data = json.loads(lesson.parsed_json)
        lesson_outline = lesson_data.get('outline', [])
        outline_stage_names = [stage.get('stage') for stage in lesson_outline]  # Populate the stage names
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Error decoding or processing lesson JSON for lesson {lesson.id}: {e}")
        # We leave lesson_outline as an empty list and outline_stage_names as an empty list

    enrollment = Enrollment.query.filter_by(user_id=current_user.id, guidelet_id=guidelet.id).first()
    
    initial_history_data = '[]'
    current_state_data = {}
    current_state_data['is_enrolled_student'] = bool(enrollment)
    current_stage_name = ""
    current_stage_index = 0

    if enrollment:
        chat_history_record = ChatHistory.query.filter_by(enrollment_id=enrollment.id, lesson_id=lesson.id).first()
        if not chat_history_record:
            chat_history_record = ChatHistory(enrollment_id=enrollment.id, lesson_id=lesson.id, history_json='[]')
            db.session.add(chat_history_record)
            db.session.commit()

        initial_history_data = chat_history_record.history_json
        
        step_index = chat_history_record.current_step_index
        lesson_steps = lesson_data.get('steps', [])

        if step_index < len(lesson_steps):
            current_stage_name = lesson_steps[step_index].get('stage', '')
            # Check if the current_stage_name is in the outline_stage_names list
            if current_stage_name in outline_stage_names:
                current_stage_index = outline_stage_names.index(current_stage_name)

        if step_index >= len(lesson_steps):
            current_state_data['is_lesson_end'] = True
            if enrollment.last_completed_chapter_number >= len(guidelet.lessons):
                current_state_data['certificate_url'] = url_for('certificate_view', guidelet_id=guidelet.id)
            else:
                current_state_data['next_chapter_url'] = url_for('student_chapter_view', guidelet_id=guidelet.id, chapter_number=lesson.chapter_number + 1)
        else:
            current_step = lesson_steps[step_index]
            step_type = current_step.get('type')
            if step_type in ['QUESTION_MCQ', 'QUESTION_SA']:
                current_state_data['question'] = current_step
    else: 
        print("\n" + "="*80)
        print(f"--- PREVIEW MODE: Processed JSON for Lesson: {lesson.id} ---")
        print(json.dumps(lesson_data, indent=2))
        print("="*80 + "\n")
        
        preview_session_key = f'preview_chat_{lesson.id}'
        if preview_session_key in session:
            del session[preview_session_key]
        
        lesson_steps = lesson_data.get("steps", [])
        if lesson_steps:
            current_stage_name = lesson_steps[0].get('stage', '')
            # FIX: Use outline_stage_names (the list of stage names) for the check
            if current_stage_name in outline_stage_names:
                current_stage_index = outline_stage_names.index(current_stage_name)

            current_step = lesson_steps[0]
            if current_step.get("type") == "MEDIA":
                media_url = current_step.get("media_url")
                if media_url:
                    current_state_data["media_url"] = media_url
                    current_state_data["media_type"] = current_step.get("media_type")
                else:
                    print(f"WARNING: Media step at index 0 has null URL in lesson {lesson.id}")

    return render_template('guidelet_player.html', 
                           guidelet=guidelet, 
                           current_lesson=lesson, 
                           enrollment=enrollment, 
                           initial_history=initial_history_data, 
                           current_state=current_state_data,
                           lesson_outline=lesson_outline,
                           current_stage_index=current_stage_index,
                           user_theme=current_user.theme if current_user.is_authenticated else 'light')
@app.route('/guidelet/<string:guidelet_id>/enroll', methods=['POST'])
@login_required
def enroll_in_guidelet(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    if current_user.id == guidelet.user_id:
        flash("You cannot enroll in a guidelet you've created.", "warning")
        return redirect(url_for('guidelet_detail_page', guidelet_id=guidelet.id))
    if current_user.is_enrolled(guidelet):
        flash("You are already enrolled in this guidelet.", "info")
        return redirect(url_for('guidelet_player', guidelet_id=guidelet.id))
    new_enrollment = Enrollment(user_id=current_user.id, guidelet_id=guidelet.id)
    db.session.add(new_enrollment)
    log_activity(current_user, 'enrolled', guidelet)
    db.session.commit()
    flash(f"You have successfully enrolled in '{guidelet.title}'!", 'success')
    return redirect(url_for('guidelet_player', guidelet_id=guidelet.id))

@app.route('/guidelet/<string:guidelet_id>/details')
def guidelet_detail_page(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    share_id = request.args.get('share_id')
    is_authorized = guidelet.status == 'published' or (current_user.is_authenticated and (current_user.id == guidelet.user_id or current_user.is_admin)) or (guidelet.shareable_link_id and guidelet.shareable_link_id == share_id)
    if not is_authorized: abort(404)
    if not current_user.is_authenticated: session['next'] = request.url
    # --- PERFORMANCE OPTIMIZATION: Efficiently query and sort reviews ---
    reviews = Review.query.filter_by(guidelet_id=guidelet.id).order_by(Review.created_at.desc()).all()
    # --- END OPTIMIZATION ---
    return render_template('guidelet_detail.html', guidelet=guidelet, share_id=share_id, reviews=reviews)

@app.route('/guidelet/<string:guidelet_id>/reviews')
def reviews_page(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    # --- PERFORMANCE OPTIMIZATION: Efficiently query and sort reviews ---
    reviews = Review.query.filter_by(guidelet_id=guidelet.id).order_by(Review.created_at.desc()).all()
    # --- END OPTIMIZATION ---
    return render_template('reviews.html', guidelet=guidelet, reviews=reviews)




@app.route('/guidelet/<string:guidelet_id>/review', methods=['POST'])
@login_required
def submit_review(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    enrollment = Enrollment.query.filter_by(user_id=current_user.id, guidelet_id=guidelet_id).first()
    if not enrollment or not enrollment.completed_at:
        flash("You must complete a guidelet before reviewing it.", "warning")
        return redirect(url_for('explore'))
    if Review.query.filter_by(user_id=current_user.id, guidelet_id=guidelet_id).first():
        flash("You have already reviewed this guidelet.", "warning")
        return redirect(url_for('reviews_page', guidelet_id=guidelet.id))
    rating = request.form.get('rating')
    comment = request.form.get('comment')
    if not rating:
        flash("A star rating is required.", "warning")
        return redirect(url_for('certificate_view', guidelet_id=guidelet.id))
    new_review = Review(rating=int(rating), comment=comment, guidelet_id=guidelet_id, user_id=current_user.id)
    db.session.add(new_review)
    db.session.commit()
    flash("Thank you for your feedback!", "success")
    return redirect(url_for('reviews_page', guidelet_id=guidelet.id))

@app.route('/guidelet/<string:guidelet_id>/certificate')
@login_required
def certificate_view(guidelet_id):
    enrollment = Enrollment.query.filter_by(user_id=current_user.id, guidelet_id=guidelet_id).first_or_404()
    
    if not enrollment.completed_at:
        flash("You have not completed this guidelet yet.", "warning")
        
        # FIXED: Use the 'guidelet_id' variable that is available to the function.
        return redirect(url_for('guidelet_player', guidelet_id=guidelet_id))

    existing_review = Review.query.filter_by(user_id=current_user.id, guidelet_id=guidelet_id).first()
    return render_template('certificate.html', enrollment=enrollment, existing_review=existing_review)

@app.route('/guidelet/<string:guidelet_id>/update_details', methods=['POST'])
@login_required
def update_guidelet_details(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    # VVV THIS IS THE CORRECTED LINE VVV
    if guidelet.creator.id != current_user.id and not current_user.is_admin: abort(403)
    
    new_title = request.form.get('title')
    if not new_title or not new_title.strip():
        flash('Guidelet title cannot be empty.', 'warning')
        return redirect(url_for('manage_guidelet', guidelet_id=guidelet.id))

    guidelet.title = new_title
    guidelet.description = request.form.get('description')

    # --- NEW: Handle Multiple PDF Uploads and Removals ---
    # 1. Handle removals
    notes_to_remove_ids = request.form.getlist('remove_note')
    for note_id in notes_to_remove_ids:
        note_to_delete = GuideletNote.query.get(note_id)
        if note_to_delete and note_to_delete.guidelet_id == guidelet.id:
            db.session.delete(note_to_delete)

    # 2. Handle new uploads
    new_pdf_files = request.files.getlist('new_notes_pdf')
    new_pdf_titles = request.form.getlist('new_note_title')

    for i, pdf_file in enumerate(new_pdf_files):
        if pdf_file and pdf_file.filename != '':
            title = new_pdf_titles[i] if i < len(new_pdf_titles) and new_pdf_titles[i] else os.path.splitext(pdf_file.filename)[0]
            
            if not pdf_file.filename.lower().endswith('.pdf'):
                flash(f"Invalid file type for '{pdf_file.filename}'. Please upload PDFs only.", 'danger')
                continue # Skip this file and proceed with others
            try:
                upload_result = cloudinary.uploader.upload(pdf_file, 
                                                           resource_type='raw', 
                                                           folder=f"coursewell_prod/{guidelet.id}/notes")
                new_note = GuideletNote(
                    guidelet_id=guidelet.id,
                    title=title,
                    url=upload_result.get('secure_url')
                )
                db.session.add(new_note)
            except Exception as e:
                flash(f"Error uploading PDF notes '{pdf_file.filename}': {e}", "danger")

    if 'thumbnail' in request.files:
        file = request.files['thumbnail']
        if file and file.filename != '':
            if not allowed_file(file.filename):
                flash('Invalid file type for thumbnail.', 'danger')
                return redirect(request.url)
            try:
                upload_result = cloudinary.uploader.upload(file, folder=f"coursewell_prod/{guidelet.id}/thumbnails")
                secure_url = upload_result.get('secure_url')
                parts = secure_url.split('/upload/')
                optimized_url = f"{parts[0]}/upload/f_auto,q_auto/{parts[1]}"
                
                guidelet.thumbnail_url = optimized_url
            except Exception as e:
                flash(f"Error uploading thumbnail: {e}", "danger")
                return redirect(request.url)
    generate_and_save_embedding(guidelet)
    db.session.commit()
    flash('Guidelet details updated successfully!', 'success')
    return redirect(url_for('manage_guidelet', guidelet_id=guidelet.id))

@app.route('/share/<string:link_id>')
def shared_guidelet_view(link_id):
    guidelet = Guidelet.query.filter_by(shareable_link_id=link_id).first_or_404()
    if not current_user.is_authenticated: session['next'] = request.url
    return render_template('course_detail.html', guidelet=guidelet, share_id=share_id)
@app.route('/guidelet/<string:guidelet_id>/generate_link', methods=['POST'])
@login_required
def generate_share_link(guidelet_id):
    guidelet = Guidelet.query.get_or_404(guidelet_id)
    if guidelet.creator.id != current_user.id: abort(403)
    if not guidelet.shareable_link_id:
        guidelet.shareable_link_id = str(uuid.uuid4())
        db.session.commit()
    return redirect(url_for('manage_guidelet', guidelet_id=guidelet.id))

@app.cli.command("admin")
@click.argument("action")
@click.argument("email")
def admin_command(action, email):
    user = User.query.filter_by(email=email).first()
    if not user:
        print(f"Error: User with email '{email}' not found.")
        return
    if action == "grant":
        user.is_admin = True
        db.session.commit()
        print(f"Success: {email} has been granted admin privileges.")
    elif action == "revoke":
        user.is_admin = False
        db.session.commit()
        print(f"Success: {email} has had their admin privileges revoked.")
    else:
        print(f"Error: Unknown action '{action}'. Use 'grant' or 'revoke'.")

@app.cli.command("reset-db")
def reset_db_command():
    """Destroys and recreates the database."""
    from sqlalchemy import text
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith("postgresql"):
        # For PostgreSQL - drop tables using SQL
        with db.engine.connect() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE;"))
            conn.execute(text("CREATE SCHEMA public;"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO public;"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO postgres;")) # Or your specific user
    elif app.config['SQLALCHEMY_DATABASE_URI'].startswith("sqlite"):
        # SQLite handling remains the same
        db_file = app.config['SQLALCHEMY_DATABASE_URI'].split("///")[1]
        if os.path.exists(db_file):
            os.remove(db_file)
    
    print("Creating all database tables from models...")
    db.create_all()
    print("Database has been reset.")

@app.cli.command("delete-user")
@click.argument("email")
def delete_user_command(email):
    """Deletes a user from the database by their email address."""
    user = User.query.filter_by(email=email).first()
    if not user:
        print(f"Error: User with email '{email}' not found.")
        return

    if click.confirm(f"Are you sure you want to delete the user {user.username} ({user.email})? This action is irreversible.", abort=True):
        db.session.delete(user)
        db.session.commit()
        print(f"Success: User {user.username} ({user.email}) has been deleted.")



@app.cli.command("search-index")
def search_index_command():
    """Generates search embeddings for all existing guidelets."""
    guidelets = Guidelet.query.all()
    total = len(guidelets)
    print(f"Starting to index {total} guidelets...")
    
    for i, guidelet in enumerate(guidelets):
        print(f"Processing ({i+1}/{total}): {guidelet.title}")
        generate_and_save_embedding(guidelet)
    
    db.session.commit()
    print("Finished indexing all guidelets.")

def format_seconds(seconds):
    """Formats total seconds into a human-readable string like 1h 2m 3s"""
    if not seconds:
        return "0s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)

# Make the helper available to all templates
app.jinja_env.filters['format_seconds'] = format_seconds

@app.route('/guidelet/<string:guidelet_id>/unenroll', methods=['POST'])
@login_required
def unenroll_from_guidelet(guidelet_id):
    """Allows a student to unenroll from a guidelet."""
    # Find the specific enrollment record for this user and guidelet.
    # first_or_404 ensures that a user can't try to unenroll from a course they aren't in.
    enrollment = Enrollment.query.filter_by(
        user_id=current_user.id,
        guidelet_id=guidelet_id
    ).first_or_404()


    guidelet_title = enrollment.guidelet.title
    db.session.delete(enrollment)
    db.session.commit()
    flash(f"You have successfully unenrolled from '{guidelet_title}'.", 'success')
    return redirect(url_for('dashboard'))


import time 

@app.context_processor
def inject_cache_buster():
    """
    Injects a cache-busting query parameter into templates.
    This is the current timestamp, which changes every time the app restarts.
    """
    return dict(cache_buster=int(time.time()))

# Add this new API endpoint in app.py
@app.route('/api/heartbeat', methods=['POST'])
@login_required
def heartbeat():
    data = request.json
    guidelet_id = data.get('guidelet_id')
    seconds = data.get('seconds', 0)

    if not guidelet_id or seconds <= 0:
        return jsonify({'status': 'error', 'message': 'Invalid data'}), 400

    # Define the Indian Standard Timezone
    ist = pytz.timezone('Asia/Kolkata')
    # Get the current date in 
    today_ist = datetime.datetime.now(ist).date()

    # Find or create the daily watch time record (UPSERT logic)
    record = DailyWatchTime.query.filter_by(
        user_id=current_user.id,
        guidelet_id=guidelet_id,
        date=today_ist
    ).first()

    if record:
        record.seconds_watched += seconds
    else:
        record = DailyWatchTime(
            user_id=current_user.id,
            guidelet_id=guidelet_id,
            date=today_ist,
            seconds_watched=seconds
        )
        db.session.add(record)
    
    db.session.commit()

    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='localhost', port=5000, debug=True)