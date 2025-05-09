from django.shortcuts import render,redirect,get_object_or_404
from store.models import Product, Variation
from .models import Cart,CartItem
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
# Create your views here.

def _cart_id(request):
    cart = request.session.session_key
    if not cart:
        cart = request.session.create()
    return cart
def add_cart(request, product_id):
    product = Product.objects.get(id=product_id)
    product_variation = []
    
    if request.method == 'POST':
        for item in request.POST:
            key = item
            value = request.POST[key]
              
            try:
                # Fix the typo here and ensure correct matching
                variation = Variation.objects.get(
                    product=product,
                    variation_category__iexact=key,  # corrected the typo
                    variation_value__iexact=value
                )
                product_variation.append(variation)
            except Variation.DoesNotExist:
                pass
    
    try:
        cart = Cart.objects.get(cart_id=_cart_id(request))
    except Cart.DoesNotExist:
        cart = Cart.objects.create(cart_id=_cart_id(request))
        cart.save()

    try:
        # Check if a CartItem with this product exists
        cart_item = CartItem.objects.get(product=product, cart=cart)
        
        if len(product_variation) > 0:
            # Avoid adding duplicate variations by checking existing ones
            existing_variations = set(cart_item.variations.all())
            for item in product_variation:
                if item not in existing_variations:
                    cart_item.variations.add(item)

        # Increase the quantity if the item already exists
        cart_item.quantity += 1
        cart_item.save()

    except CartItem.DoesNotExist:
        # If CartItem does not exist, create a new one
        cart_item = CartItem.objects.create(
            product=product,
            quantity=1,
            cart=cart,
        )
        
        # Add variations if they exist
        if len(product_variation) > 0:
            for item in product_variation:
                cart_item.variations.add(item)
        
        cart_item.save()

    return redirect('cart')


def remove_cart(request, product_id, cart_item_id):
    cart = Cart.objects.get(cart_id=_cart_id(request))
    product = get_object_or_404(Product, id=product_id)

    try:
        cart_item = CartItem.objects.get(product=product, cart=cart, id=cart_item_id)
        if cart_item.quantity > 1:
            cart_item.quantity -= 1
            cart_item.save()
        else:
            cart_item.delete()
    except CartItem.DoesNotExist:
        pass

    return redirect('cart')

def remove_cart_item(request,product_id,cart_item_id):
     cart = Cart.objects.get(cart_id=_cart_id(request))
     product = get_object_or_404(Product,id=product_id)
     cart_item = CartItem.objects.get(product=product,cart=cart,id=cart_item_id)
     cart_item.delete()
     return redirect('cart')



def cart(request, total=0,quantity=0,cart_items=None):
    try:
         tax=0
         grand_total=0
         cart = Cart.objects.get(cart_id=_cart_id(request))
         cart_items = CartItem.objects.filter(cart=cart,is_active=True)
         for cart_item in cart_items:
              total +=(cart_item.product.price * cart_item.quantity)
              quantity += cart_item.quantity
         tax =(2 * total)/100
         grand_total=total+tax
    except ObjectDoesNotExist:
         pass
    

    context = {
        'total': total,          # ← use : not =
        'quantity': quantity,
        'cart_items': cart_items,
        'tax':tax,
        'grand_total':grand_total,
} 
    return render(request, 'store/cart.html',context)