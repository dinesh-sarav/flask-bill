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
    price = db.Column(db.Float)
    tamil_name = db.Column(db.String(100))
    

    @property
    def total_stock(self):
        return sum(variant.stock for variant in self.variants)
                   
    def __repr__(self):
        return f"<Product {self.name}>"

class ProductVariant(db.Model):
    __tablename__ = 'product_variant'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    unit = db.Column(db.String(50), nullable=False)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Float, nullable=False, default=0)
    product = db.relationship('Product', back_populates='variants')

    def __repr__(self):
        return f"<Variant {self.unit} of {self.product.name} - ₹{self.price}>"

class Customer(db.Model):
    __tablename__ = 'customer'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(10), nullable=False)

    def __repr__(self):
        return f"<Customer {self.name} - {self.phone}>"

class Invoice(db.Model):
    __tablename__ = 'invoice'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    total = db.Column(db.Float, nullable=False)
    date = db.Column(db.String, default=lambda: datetime.now().strftime('%Y-%m-%d'))
    bill_no = db.Column(db.String(20), unique=True)
    total_items = db.Column(db.Integer)
    total_qty = db.Column(db.Float)
    
    customer = db.relationship('Customer', backref='invoices')
    items = db.relationship('InvoiceItem', backref ='invoice',lazy=True)

    def __repr__(self):
        return f"<Invoice #{self.id} - ₹{self.total}>"


class InvoiceItem(db.Model):
    __tablename__ = 'invoice_item'

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoice.id'))
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'))

    quantity = db.Column(db.Float, nullable=False)  # Use float for 1.5kg, etc.
    price = db.Column(db.Float, nullable=False)     # total price for this line item

    #invoice = db.relationship('Invoice', backref='items')
    variant = db.relationship('ProductVariant')

    def __repr__(self):
        return f"<InvoiceItem {self.variant.product.name} ({self.variant.unit}) x {self.quantity}>"

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True,nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
