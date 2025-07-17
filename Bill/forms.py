from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, BooleanField, FloatField, SubmitField,IntegerField, DecimalField,PasswordField ,FieldList, FormField
from wtforms.validators import DataRequired, Regexp,optional

class VariantForm(FlaskForm):
    unit = StringField("Unit (e.g. 500g, 1kg, packet)", validators=[DataRequired()])
    price = FloatField("Price", validators=[DataRequired()])
    stock = FloatField('Stock', validators=[DataRequired()])
    
class ProductForm(FlaskForm):
    name = StringField("Product Name", validators=[DataRequired()])
    tamil_name = StringField('Tamil Name', validators=[optional()])
    variants = FieldList(FormField(VariantForm), min_entries=1)
    submit = SubmitField("Save Product")

class ProductVariantForm(FlaskForm):
    unit = SelectField('Unit', choices=[
        ('kg', 'kg'),
        ('liter', 'liter'),
        ('piece', 'piece'),
        ('pack', 'pack'),
        ('box', 'box')
    ], validators=[DataRequired()])
    
    price = DecimalField('Price', validators=[DataRequired()])
    stock = IntegerField('Stock', validators=[DataRequired()])
                                              
class CustomerForm(FlaskForm):
    name = StringField("Customer Name",validators=[DataRequired()])
    phone = StringField("Customer Phone No",validators=[DataRequired(),Regexp(r'^[0-9]{10}$', message="Enter a valid 10-digit phone number")])
    submit = SubmitField("Add Customer")