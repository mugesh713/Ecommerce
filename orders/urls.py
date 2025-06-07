from django.urls import path
from . import views

urlpatterns = [
    path('place_order/', views.place_order, name='place_order'),
    path('whatsapp_payment/', views.whatsapp_payment, name='whatsapp_payment'),
    path('order_complete/', views.order_complete, name='order_complete'),
    path('cancel-order/<int:order_id>/', views.cancel_order, name='cancel_order'),

]