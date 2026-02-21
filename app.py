# app.py - Lightweight version without heavy AI dependencies
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import json
import os
from datetime import datetime, timedelta
import random
import string

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

DATA_FILE = 'atm_data.json'

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {
        'accounts': {},
        'transactions': [],
        'failed_attempts': {},
        'locked_accounts': {},
        'session_tokens': {}
    }

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)

def init_data():
    data = load_data()
    save_data(data)

init_data()

def check_account_lock(account_number):
    data = load_data()
    if account_number in data['locked_accounts']:
        lock_time = datetime.fromisoformat(data['locked_accounts'][account_number])
        if datetime.now() < lock_time + timedelta(minutes=30):
            remaining = (lock_time + timedelta(minutes=30) - datetime.now()).seconds // 60
            return True, remaining
        else:
            del data['locked_accounts'][account_number]
            if account_number in data['failed_attempts']:
                del data['failed_attempts'][account_number]
            save_data(data)
    return False, 0

def reset_daily_limits():
    data = load_data()
    now = datetime.now()
    for acc_num, account in data['accounts'].items():
        last_reset = datetime.fromisoformat(account['last_reset'])
        if now.date() > last_reset.date():
            account['daily_withdrawn'] = 0.00
            account['last_reset'] = now.isoformat()
    save_data(data)

def generate_transaction_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

def generate_account_number():
    data = load_data()
    while True:
        acc_num = ''.join(random.choices(string.digits, k=6))
        if acc_num not in data['accounts']:
            return acc_num

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name', '').strip()
    pin = data.get('pin', '')
    initial_deposit = float(data.get('initial_deposit', 0))
    
    if not name or len(name) < 2:
        return jsonify({'success': False, 'message': 'Enter valid name (min 2 characters)'}), 400
    
    if not pin or len(pin) != 4 or not pin.isdigit():
        return jsonify({'success': False, 'message': 'PIN must be 4 digits'}), 400
    
    if initial_deposit < 0:
        return jsonify({'success': False, 'message': 'Initial deposit cannot be negative'}), 400
    
    db_data = load_data()
    account_number = generate_account_number()
    
    db_data['accounts'][account_number] = {
        'pin_hash': generate_password_hash(pin),
        'balance': initial_deposit,
        'name': name,
        'account_type': 'Savings',
        'daily_limit': 5000.00,
        'daily_withdrawn': 0.00,
        'last_reset': datetime.now().isoformat(),
        'created_at': datetime.now().isoformat(),
        'preferences': {
            'fast_cash_amount': 100,
            'receipt_enabled': True,
            'language': 'en'
        }
    }
    
    if initial_deposit > 0:
        transaction = {
            'id': generate_transaction_id(),
            'type': 'deposit',
            'amount': initial_deposit,
            'timestamp': datetime.now().isoformat(),
            'balance_after': initial_deposit,
            'account_number': account_number,
            'note': 'Initial deposit'
        }
        db_data['transactions'].append(transaction)
    
    save_data(db_data)
    
    return jsonify({
        'success': True,
        'message': 'Account created successfully',
        'account': {
            'number': account_number,
            'name': name,
            'balance': initial_deposit
        }
    })

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    account_number = data.get('account_number')
    pin = data.get('pin')
    
    if not account_number or not pin:
        return jsonify({'success': False, 'message': 'Account number and PIN required'}), 400
    
    is_locked, minutes_remaining = check_account_lock(account_number)
    if is_locked:
        return jsonify({
            'success': False, 
            'message': f'Account locked. Try again in {minutes_remaining} minutes.',
            'locked': True
        }), 403
    
    db_data = load_data()
    
    if account_number not in db_data['accounts']:
        return jsonify({'success': False, 'message': 'Account not found'}), 404
    
    account = db_data['accounts'][account_number]
    
    if check_password_hash(account['pin_hash'], pin):
        if account_number in db_data['failed_attempts']:
            del db_data['failed_attempts'][account_number]
        
        session_token = generate_transaction_id()
        db_data['session_tokens'][session_token] = {
            'account_number': account_number,
            'created_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(minutes=30)).isoformat()
        }
        
        save_data(db_data)
        reset_daily_limits()
        
        return jsonify({
            'success': True,
            'token': session_token,
            'account': {
                'number': account_number,
                'name': account['name'],
                'type': account['account_type'],
                'balance': account['balance']
            }
        })
    else:
        if account_number not in db_data['failed_attempts']:
            db_data['failed_attempts'][account_number] = 0
        db_data['failed_attempts'][account_number] += 1
        
        attempts_remaining = 3 - db_data['failed_attempts'][account_number]
        
        if db_data['failed_attempts'][account_number] >= 3:
            db_data['locked_accounts'][account_number] = datetime.now().isoformat()
            save_data(db_data)
            return jsonify({
                'success': False,
                'message': 'Account locked due to 3 failed attempts. Try after 30 minutes.',
                'locked': True
            }), 403
        
        save_data(db_data)
        return jsonify({
            'success': False,
            'message': f'Invalid PIN. {attempts_remaining} attempts remaining.'
        }), 401

@app.route('/api/logout', methods=['POST'])
def logout():
    data = request.get_json()
    token = data.get('token')
    
    db_data = load_data()
    if token in db_data['session_tokens']:
        del db_data['session_tokens'][token]
        save_data(data)
    
    return jsonify({'success': True})

@app.route('/api/balance', methods=['POST'])
def get_balance():
    data = request.get_json()
    token = data.get('token')
    
    db_data = load_data()
    
    if token not in db_data['session_tokens']:
        return jsonify({'success': False, 'message': 'Session expired'}), 401
    
    session_data = db_data['session_tokens'][token]
    if datetime.now() > datetime.fromisoformat(session_data['expires_at']):
        return jsonify({'success': False, 'message': 'Session expired'}), 401
    
    account_number = session_data['account_number']
    account = db_data['accounts'][account_number]
    
    db_data['session_tokens'][token]['expires_at'] = (datetime.now() + timedelta(minutes=30)).isoformat()
    save_data(db_data)
    
    return jsonify({
        'success': True,
        'balance': account['balance'],
        'daily_limit': account['daily_limit'],
        'daily_remaining': account['daily_limit'] - account['daily_withdrawn'],
        'account_type': account['account_type']
    })

@app.route('/api/withdraw', methods=['POST'])
def withdraw():
    data = request.get_json()
    token = data.get('token')
    amount = float(data.get('amount', 0))
    note = data.get('note', '')
    
    if amount <= 0:
        return jsonify({'success': False, 'message': 'Invalid amount'}), 400
    
    if amount > 10000:
        return jsonify({'success': False, 'message': 'Maximum withdrawal limit is $10,000 per transaction'}), 400
    
    db_data = load_data()
    
    if token not in db_data['session_tokens']:
        return jsonify({'success': False, 'message': 'Session expired'}), 401
    
    session_data = db_data['session_tokens'][token]
    account_number = session_data['account_number']
    account = db_data['accounts'][account_number]
    
    if account['daily_withdrawn'] + amount > account['daily_limit']:
        remaining = account['daily_limit'] - account['daily_withdrawn']
        return jsonify({
            'success': False,
            'message': f'Daily limit exceeded. Remaining: ${remaining:.2f}'
        }), 400
    
    if amount > account['balance']:
        return jsonify({'success': False, 'message': 'Insufficient funds'}), 400
    
    account['balance'] -= amount
    account['daily_withdrawn'] += amount
    
    transaction = {
        'id': generate_transaction_id(),
        'type': 'withdrawal',
        'amount': amount,
        'timestamp': datetime.now().isoformat(),
        'balance_after': account['balance'],
        'account_number': account_number,
        'note': note
    }
    
    db_data['transactions'].append(transaction)
    db_data['session_tokens'][token]['expires_at'] = (datetime.now() + timedelta(minutes=30)).isoformat()
    save_data(db_data)
    
    return jsonify({
        'success': True,
        'new_balance': account['balance'],
        'transaction_id': transaction['id'],
        'timestamp': transaction['timestamp']
    })

@app.route('/api/deposit', methods=['POST'])
def deposit():
    data = request.get_json()
    token = data.get('token')
    amount = float(data.get('amount', 0))
    note = data.get('note', '')
    
    if amount <= 0:
        return jsonify({'success': False, 'message': 'Invalid amount'}), 400
    
    if amount > 50000:
        return jsonify({'success': False, 'message': 'Maximum deposit limit is $50,000 per transaction'}), 400
    
    db_data = load_data()
    
    if token not in db_data['session_tokens']:
        return jsonify({'success': False, 'message': 'Session expired'}), 401
    
    session_data = db_data['session_tokens'][token]
    account_number = session_data['account_number']
    account = db_data['accounts'][account_number]
    
    account['balance'] += amount
    
    transaction = {
        'id': generate_transaction_id(),
        'type': 'deposit',
        'amount': amount,
        'timestamp': datetime.now().isoformat(),
        'balance_after': account['balance'],
        'account_number': account_number,
        'note': note
    }
    
    db_data['transactions'].append(transaction)
    db_data['session_tokens'][token]['expires_at'] = (datetime.now() + timedelta(minutes=30)).isoformat()
    save_data(db_data)
    
    return jsonify({
        'success': True,
        'new_balance': account['balance'],
        'transaction_id': transaction['id'],
        'timestamp': transaction['timestamp']
    })

@app.route('/api/transfer', methods=['POST'])
def transfer():
    data = request.get_json()
    token = data.get('token')
    to_account = data.get('to_account')
    amount = float(data.get('amount', 0))
    note = data.get('note', '')
    
    if amount <= 0:
        return jsonify({'success': False, 'message': 'Invalid amount'}), 400
    
    if amount > 10000:
        return jsonify({'success': False, 'message': 'Maximum transfer limit is $10,000 per transaction'}), 400
    
    db_data = load_data()
    
    if token not in db_data['session_tokens']:
        return jsonify({'success': False, 'message': 'Session expired'}), 401
    
    session_data = db_data['session_tokens'][token]
    from_account = session_data['account_number']
    
    if from_account == to_account:
        return jsonify({'success': False, 'message': 'Cannot transfer to same account'}), 400
    
    if to_account not in db_data['accounts']:
        return jsonify({'success': False, 'message': 'Recipient account not found'}), 404
    
    sender = db_data['accounts'][from_account]
    
    if amount > sender['balance']:
        return jsonify({'success': False, 'message': 'Insufficient funds'}), 400
    
    sender['balance'] -= amount
    db_data['accounts'][to_account]['balance'] += amount
    
    transaction = {
        'id': generate_transaction_id(),
        'type': 'transfer',
        'amount': amount,
        'timestamp': datetime.now().isoformat(),
        'from_account': from_account,
        'to_account': to_account,
        'balance_after': sender['balance'],
        'note': note
    }
    
    db_data['transactions'].append(transaction)
    db_data['session_tokens'][token]['expires_at'] = (datetime.now() + timedelta(minutes=30)).isoformat()
    save_data(db_data)
    
    return jsonify({
        'success': True,
        'new_balance': sender['balance'],
        'transaction_id': transaction['id'],
        'timestamp': transaction['timestamp']
    })

@app.route('/api/transactions', methods=['POST'])
def get_transactions():
    data = request.get_json()
    token = data.get('token')
    limit = data.get('limit', 10)
    
    db_data = load_data()
    
    if token not in db_data['session_tokens']:
        return jsonify({'success': False, 'message': 'Session expired'}), 401
    
    session_data = db_data['session_tokens'][token]
    account_number = session_data['account_number']
    
    account_transactions = [
        t for t in db_data['transactions'] 
        if t.get('account_number') == account_number or 
           t.get('from_account') == account_number or 
           t.get('to_account') == account_number
    ]
    
    account_transactions.sort(key=lambda x: x['timestamp'], reverse=True)
    
    db_data['session_tokens'][token]['expires_at'] = (datetime.now() + timedelta(minutes=30)).isoformat()
    save_data(db_data)
    
    return jsonify({
        'success': True,
        'transactions': account_transactions[:limit]
    })

@app.route('/api/change-pin', methods=['POST'])
def change_pin():
    data = request.get_json()
    token = data.get('token')
    current_pin = data.get('current_pin')
    new_pin = data.get('new_pin')
    
    if not new_pin or len(new_pin) != 4 or not new_pin.isdigit():
        return jsonify({'success': False, 'message': 'PIN must be 4 digits'}), 400
    
    db_data = load_data()
    
    if token not in db_data['session_tokens']:
        return jsonify({'success': False, 'message': 'Session expired'}), 401
    
    session_data = db_data['session_tokens'][token]
    account_number = session_data['account_number']
    account = db_data['accounts'][account_number]
    
    if not check_password_hash(account['pin_hash'], current_pin):
        return jsonify({'success': False, 'message': 'Current PIN incorrect'}), 401
    
    account['pin_hash'] = generate_password_hash(new_pin)
    save_data(db_data)
    
    return jsonify({'success': True, 'message': 'PIN changed successfully'})

@app.route('/api/fast-cash', methods=['POST'])
def fast_cash():
    data = request.get_json()
    token = data.get('token')
    
    db_data = load_data()
    
    if token not in db_data['session_tokens']:
        return jsonify({'success': False, 'message': 'Session expired'}), 401
    
    session_data = db_data['session_tokens'][token]
    account_number = session_data['account_number']
    account = db_data['accounts'][account_number]
    
    amount = account['preferences']['fast_cash_amount']
    
    if amount > account['balance']:
        return jsonify({'success': False, 'message': 'Insufficient funds'}), 400
    
    if account['daily_withdrawn'] + amount > account['daily_limit']:
        return jsonify({'success': False, 'message': 'Daily limit exceeded'}), 400
    
    account['balance'] -= amount
    account['daily_withdrawn'] += amount
    
    transaction = {
        'id': generate_transaction_id(),
        'type': 'fast_cash',
        'amount': amount,
        'timestamp': datetime.now().isoformat(),
        'balance_after': account['balance'],
        'account_number': account_number
    }
    
    db_data['transactions'].append(transaction)
    db_data['session_tokens'][token]['expires_at'] = (datetime.now() + timedelta(minutes=30)).isoformat()
    save_data(db_data)
    
    return jsonify({
        'success': True,
        'amount': amount,
        'new_balance': account['balance'],
        'transaction_id': transaction['id']
    })

@app.route('/api/update-preferences', methods=['POST'])
def update_preferences():
    data = request.get_json()
    token = data.get('token')
    preferences = data.get('preferences', {})
    
    db_data = load_data()
    
    if token not in db_data['session_tokens']:
        return jsonify({'success': False, 'message': 'Session expired'}), 401
    
    session_data = db_data['session_tokens'][token]
    account_number = session_data['account_number']
    account = db_data['accounts'][account_number]
    
    account['preferences'].update(preferences)
    save_data(db_data)
    
    return jsonify({'success': True, 'preferences': account['preferences']})

@app.route('/api/account-info', methods=['POST'])
def get_account_info():
    data = request.get_json()
    token = data.get('token')
    
    db_data = load_data()
    
    if token not in db_data['session_tokens']:
        return jsonify({'success': False, 'message': 'Session expired'}), 401
    
    session_data = db_data['session_tokens'][token]
    account_number = session_data['account_number']
    account = db_data['accounts'][account_number]
    
    return jsonify({
        'success': True,
        'account': {
            'number': account_number,
            'name': account['name'],
            'type': account['account_type'],
            'balance': account['balance'],
            'daily_limit': account['daily_limit'],
            'created_at': account['created_at']
        }
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)