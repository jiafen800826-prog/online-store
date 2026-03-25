import os
import sys
import stripe
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message

from models import db, Product, CartItem, User, Order, OrderItem

# ---------------- Flask App ----------------
app = Flask(__name__)

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL',
    'sqlite:///store.db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'your-secret-key'

# ---------------- Email ----------------
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your_email@gmail.com'
app.config['MAIL_PASSWORD'] = 'your_app_password'

mail = Mail(app)

# ---------------- Upload ----------------
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------------- DB ----------------
db.init_app(app)

# ---------------- Login ----------------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ---------------- Stripe ----------------
stripe.api_key = "sk_test_YOUR_TEST_KEY"

# ---------------- Helpers ----------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ---------------- Home ----------------
@app.route('/')
def index():
    search = request.args.get('search')
    category = request.args.get('category')

    if search:
        products = Product.query.filter(Product.name.contains(search)).all()
    elif category:
        products = Product.query.filter_by(category=category).all()
    else:
        products = Product.query.all()

    # ✅ GET UNIQUE CATEGORIES
    categories = db.session.query(Product.category).distinct().all()
    categories = [c[0] for c in categories if c[0]]

    return render_template('index.html', products=products, categories=categories)

# ---------------- Auth ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if User.query.filter_by(username=username).first():
            flash("Username already exists!")
            return redirect(url_for('register'))

        user = User(username=username)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("Registered! Please login.")
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(
            username=request.form['username']
        ).first()

        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('index'))

        flash("Invalid login")

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# ---------------- Cart ----------------
@app.route('/cart')
@login_required
def cart():
    items = CartItem.query.filter_by(user_id=current_user.id).all()

    subtotal = sum(
        item.quantity * Product.query.get(item.product_id).price
        for item in items
    )

    shipping = 0 if subtotal > 50 else 5
    total = subtotal + shipping

    return render_template(
        'cart.html',
        items=items,
        subtotal=subtotal,
        shipping=shipping,
        total=total
    )


@app.route('/add_to_cart/<int:product_id>')
@login_required
def add_to_cart(product_id):
    item = CartItem.query.filter_by(
        product_id=product_id,
        user_id=current_user.id
    ).first()

    if item:
        item.quantity += 1
    else:
        item = CartItem(
            product_id=product_id,
            user_id=current_user.id,
            quantity=1
        )
        db.session.add(item)

    db.session.commit()
    return redirect(url_for('cart'))

# ---------------- Stripe Checkout ----------------
@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    items = CartItem.query.filter_by(user_id=current_user.id).all()

    line_items = []
    subtotal = 0

    for item in items:
        product = Product.query.get(item.product_id)
        subtotal += product.price * item.quantity

        line_items.append({
            'price_data': {
                'currency': 'usd',
                'product_data': {'name': product.name},
                'unit_amount': int(product.price * 100),
            },
            'quantity': item.quantity,
        })

    shipping = 0 if subtotal > 50 else 500

    if shipping > 0:
        line_items.append({
            'price_data': {
                'currency': 'usd',
                'product_data': {'name': 'Shipping'},
                'unit_amount': shipping,
            },
            'quantity': 1,
        })

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=line_items,
        mode='payment',
        success_url=url_for('success', _external=True),
        cancel_url=url_for('cart', _external=True),
    )

    return redirect(session.url, code=303)

# ---------------- Payment Success ----------------
@app.route('/success')
@login_required
def success():
    items = CartItem.query.filter_by(user_id=current_user.id).all()

    subtotal = sum(
        item.quantity * Product.query.get(item.product_id).price
        for item in items
    )

    shipping = 0 if subtotal > 50 else 5
    total = subtotal + shipping

    order = Order(
        user_id=current_user.id,
        full_name="Stripe Customer",
        address="Paid via Stripe",
        city="",
        zipcode="",
        total_amount=total,
        status="Pending"
    )

    db.session.add(order)
    db.session.commit()

    for item in items:
        db.session.add(OrderItem(
            order_id=order.id,
            product_id=item.product_id,
            quantity=item.quantity
        ))

    CartItem.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()

    # Send Email
    try:
        msg = Message(
            "Order Confirmation",
            sender=app.config['MAIL_USERNAME'],
            recipients=["customer@email.com"]
        )
        msg.body = f"Your order #{order.id} is confirmed!"
        mail.send(msg)
    except Exception as e:
        print("Email failed:", e)

    return "✅ Payment successful!"

# ---------------- Orders ----------------
@app.route('/orders')
@login_required
def orders():
    orders = Order.query.filter_by(user_id=current_user.id).all()
    return render_template('orders.html', orders=orders)

# ---------------- Admin ----------------
@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    if current_user.username != "admin":
        return "Access Denied", 403

    if request.method == 'POST':
        name = request.form['name']
        desc = request.form['description']
        price = float(request.form['price'])
        category = request.form.get('category')

        is_featured = bool(request.form.get('is_featured'))
        discount = float(request.form.get('discount', 0))

        file = request.files.get('image_file')
        image_url = None

        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            image_url = url_for('static', filename=f'uploads/{filename}')

        db.session.add(Product(
            name=name,
            description=desc,
            price=price,
            category=category,
            image_url=image_url,
            is_featured=is_featured,
            discount=discount
        ))

        db.session.commit()

    products = Product.query.all()
    return render_template('admin.html', products=products)

# ---------------- Delete ----------------
@app.route('/delete_product/<int:product_id>')
@login_required
def delete_product(product_id):
    if current_user.username != "admin":
        return "Access Denied", 403

    db.session.delete(Product.query.get_or_404(product_id))
    db.session.commit()

    return redirect(url_for('admin'))

# ---------------- Run ----------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

        if len(sys.argv) > 1 and sys.argv[1] == "create_admin":
            if not User.query.filter_by(username="admin").first():
                admin = User(username="admin")
                admin.set_password("1234")
                db.session.add(admin)
                db.session.commit()
                print("✅ Admin created!")

    app.run(debug=True)
