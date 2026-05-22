from flask import Flask, render_template, request, redirect, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user
)
from flask_socketio import SocketIO, emit, join_room
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# =========================================================
# APP CONFIG
# =========================================================

app = Flask(__name__)

app.config['SECRET_KEY'] = 'secret123'

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///social.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

login_manager = LoginManager(app)

socketio = SocketIO(app)

# =========================================================
# MODELS
# =========================================================

class User(UserMixin, db.Model):

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(
        db.String(100),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(300),
        nullable=False
    )

    is_admin = db.Column(
        db.Boolean,
        default=False
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    def set_password(self, password):

        self.password_hash = generate_password_hash(password)

    def check_password(self, password):

        return check_password_hash(
            self.password_hash,
            password
        )

class Friendship(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    sender_id = db.Column(db.Integer)

    receiver_id = db.Column(db.Integer)

    status = db.Column(
        db.String(20),
        default='pending'
    )

class Message(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    sender_id = db.Column(db.Integer)

    receiver_id = db.Column(db.Integer)

    text = db.Column(
        db.Text,
        nullable=True
    )

    sticker = db.Column(
        db.String(255),
        nullable=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    @property
    def serialize(self):

        return {

            'sender_id': self.sender_id,

            'receiver_id': self.receiver_id,

            'text': self.text,

            'sticker': self.sticker,

            'time': self.created_at.strftime('%H:%M')
        }

# =========================================================
# LOGIN MANAGER
# =========================================================

@login_manager.user_loader
def load_user(user_id):

    return db.session.get(User, int(user_id))

# =========================================================
# HOME
# =========================================================

@app.route('/')
def home():

    if current_user.is_authenticated:
        return redirect('/dashboard')

    return redirect('/login')

# =========================================================
# REGISTER
# =========================================================

@app.route('/register', methods=['GET', 'POST'])
def register():

    if request.method == 'POST':

        username = request.form['username']

        password = request.form['password']

        existing = User.query.filter_by(
            username=username
        ).first()

        if existing:
            return "Username already exists"

        total_users = User.query.count()

        user = User(username=username)

        user.set_password(password)

        # FIRST USER BECOMES ADMIN

        if total_users == 0:
            user.is_admin = True

        db.session.add(user)

        db.session.commit()

        return redirect('/login')

    return render_template('register.html')

# =========================================================
# LOGIN
# =========================================================

@app.route('/login', methods=['GET', 'POST'])
def login():

    if request.method == 'POST':

        username = request.form['username']

        password = request.form['password']

        user = User.query.filter_by(
            username=username
        ).first()

        if user and user.check_password(password):

            login_user(user)

            return redirect('/dashboard')

        return "Invalid credentials"

    return render_template('login.html')

# =========================================================
# LOGOUT
# =========================================================

@app.route('/logout')
@login_required
def logout():

    logout_user()

    return redirect('/login')

# =========================================================
# DASHBOARD
# =========================================================

@app.route('/dashboard')
@login_required
def dashboard():

    users = User.query.filter(
        User.id != current_user.id
    ).all()

    requests = Friendship.query.filter_by(
        receiver_id=current_user.id,
        status='pending'
    ).all()

    friendships = Friendship.query.filter(
        (
            (Friendship.sender_id == current_user.id)
            |
            (Friendship.receiver_id == current_user.id)
        )
        &
        (Friendship.status == 'accepted')
    ).all()

    friend_ids = []

    for friendship in friendships:

        if friendship.sender_id == current_user.id:

            friend_ids.append(friendship.receiver_id)

        else:

            friend_ids.append(friendship.sender_id)

    friends = User.query.filter(
        User.id.in_(friend_ids)
    ).all()

    return render_template(
        'dashboard.html',
        users=users,
        requests=requests,
        friends=friends
    )

# =========================================================
# SEND REQUEST
# =========================================================

@app.route('/send_request/<int:user_id>')
@login_required
def send_request(user_id):

    existing = Friendship.query.filter(
        (
            (Friendship.sender_id == current_user.id)
            &
            (Friendship.receiver_id == user_id)
        )
        |
        (
            (Friendship.sender_id == user_id)
            &
            (Friendship.receiver_id == current_user.id)
        )
    ).first()

    if not existing:

        friendship = Friendship(
            sender_id=current_user.id,
            receiver_id=user_id,
            status='pending'
        )

        db.session.add(friendship)

        db.session.commit()

    return redirect('/dashboard')

# =========================================================
# ACCEPT REQUEST
# =========================================================

@app.route('/accept/<int:req_id>')
@login_required
def accept(req_id):

    friendship = Friendship.query.get(req_id)

    if friendship:

        friendship.status = 'accepted'

        db.session.commit()

    return redirect('/dashboard')

# =========================================================
# GET MESSAGES
# =========================================================

@app.route('/messages/<int:friend_id>')
@login_required
def messages(friend_id):

    messages = Message.query.filter(
        (
            (Message.sender_id == current_user.id)
            &
            (Message.receiver_id == friend_id)
        )
        |
        (
            (Message.sender_id == friend_id)
            &
            (Message.receiver_id == current_user.id)
        )
    ).order_by(Message.created_at.asc()).all()

    return jsonify([
        message.serialize for message in messages
    ])

# =========================================================
# ADMIN PANEL
# =========================================================

@app.route('/admin')
@login_required
def admin():

    if not current_user.is_admin:
        return "Access Denied"

    users = User.query.all()

    messages = Message.query.all()

    friendships = Friendship.query.all()

    return render_template(
        'admin.html',
        users=users,
        messages=messages,
        friendships=friendships
    )

# =========================================================
# SOCKET CONNECT
# =========================================================

@socketio.on('connect')
def connect(auth=None):

    if current_user.is_authenticated:

        join_room(
            f"user_{current_user.id}"
        )

# =========================================================
# JOIN CHAT
# =========================================================

@socketio.on('join_chat')
def join_chat(data):

    friend_id = int(data['friend_id'])

    room = "_".join(
        map(
            str,
            sorted([
                current_user.id,
                friend_id
            ])
        )
    )

    join_room(room)

# =========================================================
# SEND MESSAGE
# =========================================================

@socketio.on('send_message')
def send_message(data):

    friend_id = int(data['friend_id'])

    text = data.get('text')

    sticker = data.get('sticker')

    message = Message(

        sender_id=current_user.id,

        receiver_id=friend_id,

        text=text,

        sticker=sticker
    )

    db.session.add(message)

    db.session.commit()

    room = "_".join(
        map(
            str,
            sorted([
                current_user.id,
                friend_id
            ])
        )
    )

    emit(
        'receive_message',
        {
            'sender_id': message.sender_id,
            'receiver_id': message.receiver_id,
            'text': message.text,
            'sticker': message.sticker,
            'time': message.created_at.strftime('%H:%M')
        },
        room=room
    )

# =========================================================
# CREATE DATABASE
# =========================================================

with app.app_context():

    db.create_all()

# =========================================================
# RUN APP
# =========================================================

if __name__ == '__main__':

    socketio.run(
        app,
        debug=True
    )