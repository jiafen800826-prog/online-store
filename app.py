import os
import stripe
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_migrate import Migrate
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from itsdangerous.exc import SignatureExpired, BadSignature
from datetime import datetime
basedir = os.path.abspath(os.path.dirname(__file__))

from sqlalchemy import text

from models import db, Product, User, Review, CartItem, Order, OrderItem, WishlistItem, ProductImage


app = Flask(__name__)

if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///" + os.path.join(basedir, "store.db")
print("DB URI:", app.config["SQLALCHEMY_DATABASE_URI"])
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

app.config["STRIPE_PUBLIC_KEY"] = os.environ.get("STRIPE_PUBLIC_KEY")
app.config["STRIPE_SECRET_KEY"] = os.environ.get("STRIPE_SECRET_KEY")
app.config["STRIPE_WEBHOOK_SECRET"] = os.environ.get("STRIPE_WEBHOOK_SECRET")

app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_USERNAME")

mail = Mail(app)
stripe.api_key = app.config["STRIPE_SECRET_KEY"]

db.init_app(app)
migrate = Migrate(app, db)

UPLOAD_FOLDER = "static/uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_reset_serializer():
    return URLSafeTimedSerializer(app.config["SECRET_KEY"])


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route("/")
def index():
    category = request.args.get("category")
    search = request.args.get("search")

    query = Product.query

    if category:
        query = query.filter_by(category=category)
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))

    products = query.all()

    categories = db.session.query(Product.category).distinct().all()
    categories = [c[0] for c in categories if c[0]]

    product_ratings = {}
    for product in products:
        reviews = Review.query.filter_by(product_id=product.id).all()
        if reviews:
            product_ratings[product.id] = sum(r.rating for r in reviews) / len(reviews)
        else:
            product_ratings[product.id] = 0

    return render_template(
        "index.html",
        products=products,
        categories=categories,
        product_ratings=product_ratings
    )


@app.route("/db-check")
def db_check():
    try:
        result = db.session.execute(text("SELECT 1")).scalar()
        return f"Database connected successfully: {result}"
    except Exception as e:
        return f"Database connection failed: {str(e)}", 500

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if User.query.filter_by(username=username).first():
            flash("Username already exists.")
            return redirect(url_for("register"))

        if User.query.filter_by(email=email).first():
            flash("Email already exists.")
            return redirect(url_for("register"))

        user = User(username=username, email=email)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("Registration successful. Please log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash("Logged in successfully.")
            return redirect(url_for("index"))

        flash("Invalid username or password.")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.")
    return redirect(url_for("index"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        user = User.query.filter_by(email=email).first()

        if user:
            s = get_reset_serializer()
            token = s.dumps(user.email, salt="password-reset")
            reset_link = url_for("reset_password", token=token, _external=True)

            msg = Message(
                subject="Reset Your Password",
                recipients=[user.email],
                body=f"Click this link to reset your password:\n\n{reset_link}"
            )
            mail.send(msg)

        flash("If that email exists, a reset link was sent.")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    s = get_reset_serializer()

    try:
        email = s.loads(token, salt="password-reset", max_age=3600)
    except SignatureExpired:
        flash("Reset link expired.")
        return redirect(url_for("forgot_password"))
    except BadSignature:
        flash("Invalid reset link.")
        return redirect(url_for("forgot_password"))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("User not found.")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for("reset_password", token=token))

        user.set_password(password)
        db.session.commit()

        flash("Password reset successful. Please log in.")
        return redirect(url_for("login"))

    return render_template("reset_password.html")


@app.route("/admin")
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        return "Access Denied", 403

    products = Product.query.all()
    orders = Order.query.all()

    total_products = len(products)
    total_orders = len(orders)
    total_users = User.query.count()
    total_revenue = sum(order.total_amount or 0 for order in orders)

    recent_orders = Order.query.order_by(Order.id.desc()).limit(5).all()
    low_stock_products = Product.query.filter(Product.stock < 5).all()

    dates = [f"Order {o.id}" for o in orders]
    order_counts = [1 for _ in orders]
    revenue_data = [o.total_amount or 0 for o in orders]

    return render_template(
        "admin_dashboard.html",
        total_products=total_products,
        total_orders=total_orders,
        total_users=total_users,
        total_revenue=total_revenue,
        recent_orders=recent_orders,
        low_stock_products=low_stock_products,
        dates=dates,
        order_counts=order_counts,
        revenue_data=revenue_data
    )


@app.route("/admin/create_user", methods=["GET", "POST"])
@login_required
def admin_create_user():
    if not current_user.is_admin:
        return "Access Denied", 403

    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        is_admin = "is_admin" in request.form

        if User.query.filter_by(username=username).first():
            flash("Username already exists.")
            return redirect(url_for("admin_create_user"))

        if User.query.filter_by(email=email).first():
            flash("Email already exists.")
            return redirect(url_for("admin_create_user"))

        user = User(
            username=username,
            email=email,
            is_admin=is_admin
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        flash("User created successfully.")
        return redirect(url_for("admin_create_user"))

    users = User.query.order_by(User.id.desc()).all()
    return render_template("admin_create_user.html", users=users)


@app.route("/admin/products", methods=["GET", "POST"])
@login_required
def admin_products():
    if not current_user.is_admin:
        return "Access Denied", 403

    if request.method == "POST":
        name = request.form["name"]
        description = request.form["description"]
        price = float(request.form["price"])
        stock = int(request.form.get("stock", 0))
        category = request.form.get("category", "")
        is_featured = "is_featured" in request.form
        discount = float(request.form.get("discount", 0))

        file = request.files.get("image_file")
        image_url = None

        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            image_url = url_for("static", filename=f"uploads/{filename}")

        product = Product(
            name=name,
            description=description,
            price=price,
            stock=stock,
            category=category,
            is_featured=is_featured,
            discount=discount,
            image_url=image_url
        )

        db.session.add(product)
        db.session.commit()

        gallery_files = request.files.getlist("gallery_images")
        for gallery_file in gallery_files:
            if gallery_file and gallery_file.filename and allowed_file(gallery_file.filename):
                filename = secure_filename(gallery_file.filename)
                gallery_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                gallery_image_url = url_for("static", filename=f"uploads/{filename}")

                gallery_image = ProductImage(
                    product_id=product.id,
                    image_url=gallery_image_url
                )
                db.session.add(gallery_image)

        db.session.commit()

        flash("Product added successfully.")
        return redirect(url_for("admin_products"))

    search = request.args.get("search", "")
    category = request.args.get("category", "")

    query = Product.query

    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))

    if category:
        query = query.filter_by(category=category)

    products = query.all()

    categories = db.session.query(Product.category).distinct().all()
    categories = [c[0] for c in categories if c[0]]

    low_stock_products = Product.query.filter(Product.stock < 5).all()

    return render_template(
        "admin_products.html",
        products=products,
        low_stock_products=low_stock_products,
        categories=categories,
        search=search,
        selected_category=category
    )


@app.route("/admin/edit_product/<int:product_id>", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    if not current_user.is_admin:
        return "Access Denied", 403

    product = Product.query.get_or_404(product_id)

    if request.method == "POST":
        product.name = request.form["name"]
        product.description = request.form["description"]
        product.category = request.form.get("category", "")
        product.price = float(request.form["price"])
        product.stock = int(request.form.get("stock", 0))
        product.is_featured = "is_featured" in request.form
        product.discount = float(request.form.get("discount", 0))

        file = request.files.get("image_file")
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            product.image_url = url_for("static", filename=f"uploads/{filename}")

        gallery_files = request.files.getlist("gallery_images")
        for gallery_file in gallery_files:
            if gallery_file and gallery_file.filename and allowed_file(gallery_file.filename):
                filename = secure_filename(gallery_file.filename)
                gallery_file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
                gallery_image_url = url_for("static", filename=f"uploads/{filename}")

                gallery_image = ProductImage(
                    product_id=product.id,
                    image_url=gallery_image_url
                )
                db.session.add(gallery_image)

        db.session.commit()
        flash("Product updated successfully.")
        return redirect(url_for("admin_products"))

    return render_template("edit_product.html", product=product)


@app.route("/admin/delete_product/<int:product_id>", methods=["POST"])
@login_required
def delete_product(product_id):
    if not current_user.is_admin:
        return "Access Denied", 403

    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()

    flash("Product deleted successfully.")
    return redirect(url_for("admin_products"))


@app.route("/admin/orders")
@login_required
def admin_orders():
    if not current_user.is_admin:
        return "Access Denied", 403

    orders = Order.query.order_by(Order.created_at.desc()).all()
    order_items = OrderItem.query.all()

    return render_template(
        "admin_orders.html",
        orders=orders,
        order_items=order_items
    )


@app.route("/admin/update_order_status/<int:order_id>", methods=["POST"])
@login_required
def update_order_status(order_id):
    if not current_user.is_admin:
        return "Access Denied", 403

    order = Order.query.get_or_404(order_id)
    new_status = request.form.get("status")

    allowed_statuses = ["Pending", "Paid", "Shipped", "Delivered", "Cancelled"]

    if new_status not in allowed_statuses:
        flash("Invalid order status.")
        return redirect(url_for("admin_orders"))

    order.status = new_status
    db.session.commit()

    flash(f"Order #{order.id} updated to {new_status}.")
    return redirect(url_for("admin_orders"))

@app.route('/admin/reject-cancel/<int:order_id>', methods=['POST'])
@login_required
def reject_cancel(order_id):
    if not current_user.is_admin:
        flash("Access denied.")
        return redirect(url_for('index'))

    order = Order.query.get_or_404(order_id)

    if order.cancel_status != "Pending":
        flash("This cancellation request is not pending.")
        return redirect(url_for('admin_orders'))

    order.cancel_status = "Rejected"

    db.session.commit()
    flash(f"Cancellation rejected for Order #{order.id}.")
    return redirect(url_for('admin_orders'))


@app.route("/product/<int:product_id>", methods=["GET", "POST"])
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    reviews = Review.query.filter_by(product_id=product_id).all()

    if request.method == "POST":
        if not current_user.is_authenticated:
            flash("Please log in to leave a review.")
            return redirect(url_for("login"))

        rating = int(request.form["rating"])
        comment = request.form["comment"]

        existing_review = Review.query.filter_by(
            product_id=product.id,
            user_id=current_user.id
        ).first()

        if existing_review:
            existing_review.rating = rating
            existing_review.comment = comment
        else:
            review = Review(
                product_id=product.id,
                user_id=current_user.id,
                rating=rating,
                comment=comment
            )
            db.session.add(review)

        db.session.commit()
        flash("Review submitted successfully.")
        return redirect(url_for("product_detail", product_id=product.id))

    avg_rating = 0
    if reviews:
        avg_rating = sum(r.rating for r in reviews) / len(reviews)

    return render_template(
        "product_detail.html",
        product=product,
        reviews=reviews,
        avg_rating=avg_rating
    )


@app.route("/add_to_cart/<int:product_id>")
@login_required
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)

    if product.stock <= 0:
        flash("This product is out of stock.")
        return redirect(url_for("product_detail", product_id=product.id))

    existing_item = CartItem.query.filter_by(
        user_id=current_user.id,
        product_id=product.id
    ).first()

    if existing_item:
        if existing_item.quantity < product.stock:
            existing_item.quantity += 1
        else:
            flash("You cannot add more than available stock.")
            return redirect(url_for("cart"))
    else:
        cart_item = CartItem(
            user_id=current_user.id,
            product_id=product.id,
            quantity=1
        )
        db.session.add(cart_item)

    db.session.commit()
    flash("Product added to cart.")
    return redirect(url_for("cart"))


@app.route("/cart")
@login_required
def cart():
    items = CartItem.query.filter_by(user_id=current_user.id).all()

    subtotal = sum(item.quantity * item.product.price for item in items)
    shipping = 0 if subtotal > 50 else 5
    total = subtotal + shipping

    return render_template(
        "cart.html",
        items=items,
        subtotal=subtotal,
        shipping=shipping,
        total=total
    )


@app.route("/update_cart/<int:item_id>", methods=["POST"])
@login_required
def update_cart(item_id):
    item = CartItem.query.get_or_404(item_id)

    if item.user_id != current_user.id:
        return "Access Denied", 403

    quantity = int(request.form.get("quantity", 1))

    if quantity <= 0:
        db.session.delete(item)
    elif quantity > item.product.stock:
        flash("Quantity exceeds available stock.")
        return redirect(url_for("cart"))
    else:
        item.quantity = quantity

    db.session.commit()
    flash("Cart updated.")
    return redirect(url_for("cart"))


@app.route("/remove_from_cart/<int:item_id>", methods=["POST"])
@login_required
def remove_from_cart(item_id):
    item = CartItem.query.get_or_404(item_id)

    if item.user_id != current_user.id:
        return "Access Denied", 403

    db.session.delete(item)
    db.session.commit()

    flash("Item removed from cart.")
    return redirect(url_for("cart"))


@app.route("/checkout", methods=["POST"])
@login_required
def checkout():
    items = CartItem.query.filter_by(user_id=current_user.id).all()

    if not items:
        flash("Your cart is empty.")
        return redirect(url_for("cart"))

    line_items = []

    for item in items:
        if item.quantity > item.product.stock:
            flash(f"Not enough stock for {item.product.name}.")
            return redirect(url_for("cart"))

        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": item.product.name
                },
                "unit_amount": int(item.product.price * 100)
            },
            "quantity": item.quantity
        })

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url=url_for("payment_success", _external=True),
            cancel_url=url_for("payment_cancel", _external=True)
        )
        return redirect(checkout_session.url, code=303)

    except Exception as e:
        return f"Stripe error: {str(e)}", 500

@app.route("/payment-success")
@login_required
def payment_success():
    items = CartItem.query.filter_by(user_id=current_user.id).all()

    if items:
        subtotal = sum(item.quantity * item.product.price for item in items)
        shipping = 0 if subtotal > 50 else 5
        total = subtotal + shipping

        order = Order(
            user_id=current_user.id,
            total_amount=total,
            status="Paid"
        )
        db.session.add(order)
        db.session.flush()

        for item in items:
            order_item = OrderItem(
                order_id=order.id,
                product_id=item.product_id,
                quantity=item.quantity,
                price_at_purchase=item.product.price,
                product_name_snapshot=item.product.name
            )
            db.session.add(order_item)
            item.product.stock -= item.quantity

        CartItem.query.filter_by(user_id=current_user.id).delete()
        db.session.commit()

    return render_template("payment_success.html")


@app.route("/payment-cancel")
@login_required
def payment_cancel():
    flash("Payment was cancelled.")
    return render_template("payment_cancel.html")


@app.route("/my_orders")
@login_required
def my_orders():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template("my_orders.html", orders=orders)


@app.route("/order/<int:order_id>")
@login_required
def order_detail(order_id):
    order = Order.query.get_or_404(order_id)

    if order.user_id != current_user.id and not current_user.is_admin:
        return "Access Denied", 403

    return render_template("order_detail.html", order=order)


@app.route("/add_to_wishlist/<int:product_id>")
@login_required
def add_to_wishlist(product_id):
    product = Product.query.get_or_404(product_id)

    existing_item = WishlistItem.query.filter_by(
        user_id=current_user.id,
        product_id=product.id
    ).first()

    if existing_item:
        flash("Already in your wishlist.")
    else:
        item = WishlistItem(user_id=current_user.id, product_id=product.id)
        db.session.add(item)
        db.session.commit()
        flash("Added to wishlist.")

    return redirect(url_for("product_detail", product_id=product.id))


@app.route("/wishlist")
@login_required
def wishlist():
    items = WishlistItem.query.filter_by(user_id=current_user.id).all()
    return render_template("wishlist.html", items=items)


@app.route("/remove_from_wishlist/<int:item_id>", methods=["POST"])
@login_required
def remove_from_wishlist(item_id):
    item = WishlistItem.query.get_or_404(item_id)

    if item.user_id != current_user.id:
        return "Access Denied", 403

    db.session.delete(item)
    db.session.commit()
    flash("Removed from wishlist.")
    return redirect(url_for("wishlist"))



@app.route('/admin/cancel_order/<int:order_id>', methods=['POST'])
@login_required
def cancel_order(order_id):
    if not current_user.is_admin:
        return "Access Denied", 403

    order = Order.query.get_or_404(order_id)

    if order.status in ['Shipped', 'Delivered']:
        flash("Cannot cancel shipped or delivered orders.")
        return redirect(url_for('admin_orders'))

    order.status = "Cancelled"

    for item in order.items:
        product = Product.query.get(item.product_id)
        if product:
            product.stock += item.quantity

    db.session.commit()
    flash("Order cancelled and stock restored.")
    return redirect(url_for('admin_orders'))

@app.route('/admin/update_shipping/<int:order_id>', methods=['POST'])
@login_required
def update_shipping(order_id):
    if not current_user.is_admin:
        return "Access Denied", 403

    order = Order.query.get_or_404(order_id)

    order.shipping_carrier = request.form.get('shipping_carrier')
    order.tracking_number = request.form.get('tracking_number')
    order.shipping_status = request.form.get('shipping_status', 'Not shipped')

    if order.shipping_status == 'Shipped' and not order.shipped_at:
        order.shipped_at = datetime.utcnow()

    if order.shipping_status == 'Shipped':
        order.status = 'Shipped'
    elif order.shipping_status == 'Delivered':
        order.status = 'Delivered'

    db.session.commit()
    flash("Shipping updated.")
    return redirect(url_for('admin_orders'))

@app.route('/request_return/<int:order_id>', methods=['POST'])
@login_required
def request_return(order_id):
    order = Order.query.get_or_404(order_id)

    if order.user_id != current_user.id:
        return "Access Denied", 403

    if order.status != 'Delivered':
        flash("You can only request a return after delivery.")
        return redirect(url_for('order_detail', order_id=order.id))

    order.return_requested = True
    order.return_reason = request.form.get('return_reason', '')
    order.return_status = "Requested"

    db.session.commit()
    flash("Return request submitted.")
    return redirect(url_for('order_detail', order_id=order.id))


@app.route('/admin/approve-cancel/<int:order_id>', methods=['POST'])
@login_required
def approve_cancel(order_id):
    if not current_user.is_admin:
        flash("Access denied.")
        return redirect(url_for('index'))

    order = Order.query.get_or_404(order_id)

    if order.cancel_status != "Pending":
        flash("This cancellation request is not pending.")
        return redirect(url_for('admin_orders'))

    order.cancel_status = "Approved"
    order.status = "Cancelled"

    db.session.commit()
    flash(f"Cancellation approved for Order #{order.id}.")
    return redirect(url_for('admin_orders'))

@app.route('/orders')
@login_required
def orders():
    user_orders = Order.query.filter_by(user_id=current_user.id)\
        .order_by(Order.created_at.desc())\
        .all()

    return render_template('orders.html', orders=user_orders)

@app.route('/request-cancel/<int:order_id>', methods=['POST'])
@login_required
def request_cancel(order_id):
    order = Order.query.get_or_404(order_id)

    if order.user_id != current_user.id:
        flash("You cannot cancel this order.")
        return redirect(url_for('order_detail', order_id=order.id))

    if order.status in ['Shipped', 'Delivered', 'Cancelled']:
        flash("This order can no longer be cancelled.")
        return redirect(url_for('order_detail', order_id=order.id))

    if order.cancel_requested:
        flash("Cancellation has already been requested for this order.")
        return redirect(url_for('order_detail', order_id=order.id))

    reason = request.form.get('cancel_reason', '').strip()

    if not reason:
        flash("Please enter a cancellation reason.")
        return redirect(url_for('order_detail', order_id=order.id))

    order.cancel_requested = True
    order.cancel_reason = reason
    order.cancel_status = "Pending"

    db.session.commit()

    flash("Cancellation request submitted.")
    return redirect(url_for('order_detail', order_id=order.id))

if __name__ == "__main__":
    with app.app_context():
        db.create_all()

        admin_user = User.query.filter_by(username="admin").first()
        if not admin_user:
            admin_user = User(
                username="admin",
                email="admin@example.com",
                is_admin=True
            )
            admin_user.set_password("1234")
            db.session.add(admin_user)
            db.session.commit()

    app.run(debug=True)