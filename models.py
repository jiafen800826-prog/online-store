from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

# ---------------- User ----------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    is_admin = db.Column(db.Boolean, default=False)

    orders = db.relationship('Order', backref='user', lazy=True)
    cart_items = db.relationship('CartItem', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


# ---------------- Product ----------------
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100))
    description = db.Column(db.String(200))
    price = db.Column(db.Float)

    image_url = db.Column(db.String(300))
    is_featured = db.Column(db.Boolean, default=False)
    discount = db.Column(db.Float, default=0)
    category = db.Column(db.String(100))

    stock = db.Column(db.Integer, default=0)


# ---------------- Product Images ----------------
class ProductImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    image_url = db.Column(db.String(300))

    product = db.relationship('Product', backref='gallery_images')


# ---------------- Cart ----------------
class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    quantity = db.Column(db.Integer, default=1)

    product = db.relationship('Product')


# ---------------- Order ----------------
class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    full_name = db.Column(db.String(100))
    address = db.Column(db.String(200))
    city = db.Column(db.String(100))
    zipcode = db.Column(db.String(20))

    total_amount = db.Column(db.Float)
    status = db.Column(db.String(50), default="Pending")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    items = db.relationship('OrderItem', backref='order', lazy=True)

    cancel_requested = db.Column(db.Boolean, default=False)
    cancel_reason = db.Column(db.String(300))
    cancel_status = db.Column(db.String(100), default="No request")

    tracking_number = db.Column(db.String(100))
    shipping_carrier = db.Column(db.String(100))
    shipping_status = db.Column(db.String(100), default="Not shipped")
    shipped_at = db.Column(db.DateTime)

    return_requested = db.Column(db.Boolean, default=False)
    return_reason = db.Column(db.String(300))
    return_status = db.Column(db.String(100), default="No return")

    return_label_url = db.Column(db.String(300))

# ---------------- Order Items ----------------
class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    order_id = db.Column(db.Integer, db.ForeignKey('order.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))

    quantity = db.Column(db.Integer)

    price_at_purchase = db.Column(db.Float)  # ⭐ IMPORTANT
    product_name_snapshot = db.Column(db.String(100))  # ⭐ IMPORTANT

    product = db.relationship('Product')


# ---------------- Wishlist ----------------
class WishlistItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))

    product = db.relationship('Product')


# ---------------- Review ----------------
class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    rating = db.Column(db.Integer)
    comment = db.Column(db.String(300))

    product = db.relationship('Product', backref='reviews')
    user = db.relationship('User')
