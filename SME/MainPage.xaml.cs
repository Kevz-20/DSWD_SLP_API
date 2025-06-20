using System;
using Microsoft.Maui.Controls;
using SME.Models;
using Microsoft.Maui.Storage;
using System.Threading.Tasks;

namespace SME
{
    public partial class MainPage : ContentPage
    {
        private string _pinEntered = "";
        private SME.Models.Account account;
        private readonly ApiService apiService = new ApiService();

        public MainPage()
        {
            InitializeComponent();
            NavigationPage.SetHasNavigationBar(this, false);
        }

        protected override async void OnAppearing()
        {
            base.OnAppearing();

            var savedPhone = await SecureStorage.GetAsync("selectedPhoneNumber");

            if (!string.IsNullOrEmpty(savedPhone))
            {
                App.CurrentPhoneNumber = savedPhone; // ✅ keep global in sync
                AccountNumberButton.Text = $"Account Number: {savedPhone}";
                await LoadAccountInfo(savedPhone);
            }
            else
            {
                AccountNumberButton.Text = "Account Number: 09XXXXXXXXX";
            }
        }

        // ✅ Load account by phone number
        private async Task LoadAccountInfo(string phone)
        {
            account = await apiService.GetAccountAsync(phone);
        }

        private async void OnCreateNewAccountClicked(object sender, EventArgs e)
        {
            await Navigation.PushAsync(new CreateNewAccountPage());
        }

        private async void OnForgotPinClicked(object sender, EventArgs e)
        {
            await Navigation.PushAsync(new ForgotPage());
        }

        // ✅ Switch account number
        private async void OnAccountNumberButtonClicked(object sender, EventArgs e)
        {
            string newNumber = await DisplayPromptAsync("Switch Account", "Enter Phone Number:");
            if (!string.IsNullOrWhiteSpace(newNumber))
            {
                await SecureStorage.SetAsync("selectedPhoneNumber", newNumber);
                App.CurrentPhoneNumber = newNumber;
                AccountNumberButton.Text = $"Account Number: {newNumber}";
                await LoadAccountInfo(newNumber);
            }
        }

        private void OnNumpadClicked(object sender, EventArgs e)
        {
            if (sender is Button button && _pinEntered.Length < 4)
            {
                _pinEntered += button.Text;
                UpdatePinDisplay();
            }
        }

        private void UpdatePinDisplay()
        {
            DotFrame1.BackgroundColor = _pinEntered.Length > 0 ? Color.FromArgb("#FFFFFF") : Color.FromArgb("00000000");
            DotFrame2.BackgroundColor = _pinEntered.Length > 1 ? Color.FromArgb("#FFFFFF") : Color.FromArgb("00000000");
            DotFrame3.BackgroundColor = _pinEntered.Length > 2 ? Color.FromArgb("#FFFFFF") : Color.FromArgb("00000000");
            DotFrame4.BackgroundColor = _pinEntered.Length > 3 ? Color.FromArgb("#FFFFFF") : Color.FromArgb("00000000");
        }

        private async void OnLoginClicked(object sender, EventArgs e)
        {
            string pin = _pinEntered.Trim();
            string phoneNumber = App.CurrentPhoneNumber?.Trim() ?? "";

            // Call updated LoginAsync
            var errorMessage = await apiService.LoginAsync(phoneNumber, pin);

            if (string.IsNullOrEmpty(errorMessage))
            {
                _pinEntered = "";
                UpdatePinDisplay();
                await Navigation.PushAsync(new HomePage()); // Login successful
            }
            else
            {
                await DisplayAlert("Failed", errorMessage, "OK");
                _pinEntered = "";
                UpdatePinDisplay();
            }
        }

        private void OnBackspaceClicked(object sender, EventArgs e)
        {
            if (_pinEntered.Length > 0)
            {
                _pinEntered = _pinEntered[..^1];
                UpdatePinDisplay();
            }
        }
    }
}
