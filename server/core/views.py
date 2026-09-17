from django.http import HttpResponse

def home(request):
    return HttpResponse("PrimeTime Taxi v2 backend is running.")


