from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render


class SignUpForm(UserCreationForm):
    """Signup form with account profile fields."""

    email = forms.EmailField(required=True)
    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)

    class Meta(UserCreationForm.Meta):
        fields = (
            "username",
            "email",
            "first_name",
            "last_name",
            "password1",
            "password2",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.order_fields(["username", "email", "first_name", "last_name", "password1", "password2"])

        self.fields["username"].label = "Username"
        self.fields["email"].label = "Email"
        self.fields["first_name"].label = "First name"
        self.fields["last_name"].label = "Last name"
        self.fields["password1"].label = "Password"
        self.fields["password2"].label = "Password confirmation"

    def clean_username(self):
        username = self.cleaned_data["username"].strip().lower()

        User = get_user_model()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already in use.")

        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        User = get_user_model()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("This email is already in use.")

        return email

    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip()

    def clean_last_name(self):
        return self.cleaned_data["last_name"].strip()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]

        if commit:
            user.save()

        return user

def signup(request):
    """Create a user account, then log the user in."""

    # If the request is a POST then the user has signed up
    if request.method == "POST":
        form = SignUpForm(request.POST)

        # Check if the form is valid and if so save the user and log them in
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("file_list")
    # Otherwise, the user is just viewing the signup page so show them the form
    else:
        form = SignUpForm()

    return render(request, "accounts/signup.html", {"form": form})

@login_required
def profile(request):
    """Display the current user's profile information."""

    return render(
        request,
        "accounts/profile.html",
        {
            "profile_user": request.user,
        },
    )
