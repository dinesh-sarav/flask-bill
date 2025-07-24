from extensions import db
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class Product(db.Model):
    __tablename__ = 'product'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    variants = db.relationship('ProductVariant', back_populates='product', cascade='all, delete-orphan')
    sold_by = db.Column(db.String(20))
    # price = db.Column(db.Float) # This 'price' on Product model might be redundant if variants have prices
    tamil_name = db.Column(db.String(100))
    romanized_name = db.Column(db.String(100))
    barcode = db.Column(db.String(100), unique=True) # Product-level barcode, consider if really needed given variant barcodes

    @property
    def total_stock(self):
        # Ensure variants are loaded before summing stock
        return sum(variant.stock for variant in self.variants if variant.stock is not None)

    def __repr__(self):
        return f"<Product {self.name}>"

class ProductVariant(db.Model):
    __tablename__ = 'product_variant'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    unit = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, nullable=False, default=0)
    product = db.relationship('Product', back_populates='variants')
    barcode = db.Column(db.String(100), unique=True) # Variant-level barcode (more common)
    initial_stock = db.Column(db.Integer, nullable=False, default=0)

    def __repr__(self):
        return f"<Variant {self.unit} of {self.product.name} - ₹{self.price}>"

class Customer(db.Model):
    __tablename__ = 'customer'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(10), nullable=False, unique=True) # Phone number should be unique
    def __repr__(self):
        return f"<Customer {self.name} - {self.phone}>"

class Invoice(db.Model):
    __tablename__ = 'invoice'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    total = db.Column(db.Float, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow) # Store as DateTime object
    bill_no = db.Column(db.String(20), unique=True)
    total_items = db.Column(db.Integer, default=0, nullable=False) 
    total_qty = db.Column(db.Float, default=0, nullable=False)    

    customer = db.relationship('Customer', backref='invoices')
    items = db.relationship('InvoiceItem', backref ='invoice', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Invoice #{self.id} - ₹{self.total}>"

class InvoiceItem(db.Model):
    __tablename__ = 'invoice_item'

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'))
    quantity = db.Column(db.Float, nullable=False)
    price = db.Column(db.Float, nullable=False) # Price of the variant at the time of sale (unit price)
    variant = db.relationship('ProductVariant')

    def __repr__(self):
        return f"<InvoiceItem {self.variant.product.name} ({self.variant.unit}) x {self.quantity}>"

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True,nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    email_verified = db.Column(db.Boolean, default=False)
    reset_token = db.Column(db.String(100), nullable=True)
    verification_token = db.Column(db.String(100), nullable=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# --- NEW MODELS FOR MULTIPLE BILL SUPPORT ---
class ActiveCart(db.Model):
    __tablename__ = 'active_cart'

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='open') # e.g., 'open', 'completed', 'cancelled'
    total_amount = db.Column(db.Float, default=0.0) # Total amount for this active cart
    items = db.relationship('ActiveCartItem', backref='cart', lazy=True, cascade="all, delete-orphan") # Added items relationship

    def __repr__(self):
        return f"<ActiveCart {self.id} (Status: {self.status})>"

class ActiveCartItem(db.Model):
    __tablename__ = 'active_cart_item'

    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey('active_cart.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    price_at_time_of_add = db.Column(db.Float, nullable=False) # Store unit price at time of add

    variant = db.relationship('ProductVariant', backref='active_cart_items')

    def __repr__(self):
        return f"<ActiveCartItem Cart:{self.cart_id} Variant:{self.variant_id} Qty:{self.quantity}>"
