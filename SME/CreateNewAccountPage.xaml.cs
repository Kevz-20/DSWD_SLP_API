using System;
using Microsoft.Maui.Controls;
using SME.Models;
using Microsoft.Maui.Storage;

namespace SME
{
    public partial class CreateNewAccountPage : ContentPage
    {
        public CreateNewAccountPage()
        {
            InitializeComponent();
            NavigationPage.SetHasNavigationBar(this, false); // Hide navigation bar
        }

        private async void OnCreateAccountClicked(object sender, EventArgs e)
        {
            string firstName = FirstNameEntry.Text?.Trim();
            string middleName = MiddleNameEntry.Text?.Trim();
            string lastName = LastNameEntry.Text?.Trim();
            string contact = ContactEntry.Text?.Trim();
            string pin = PinEntry.Text;
            string confirmPin = ConfirmPinEntry.Text;

            if (string.IsNullOrWhiteSpace(firstName) ||
                string.IsNullOrWhiteSpace(lastName) ||
                string.IsNullOrWhiteSpace(contact) ||
                string.IsNullOrWhiteSpace(pin) ||
                string.IsNullOrWhiteSpace(confirmPin))
            {
                await DisplayAlert("Missing Info", "Please fill in all required fields.", "OK");
                return;
            }

            if (pin.Length != 4 || confirmPin.Length != 4)
            {
                await DisplayAlert("Invalid PIN", "PIN must be exactly 4 digits.", "OK");
                return;
            }

            if (pin != confirmPin)
            {
                await DisplayAlert("PIN Mismatch", "PIN and confirmation do not match.", "OK");
                return;
            }

            var account = new Account
            {
                FirstName = FirstNameEntry.Text,
                MiddleName = MiddleNameEntry.Text,
                LastName = LastNameEntry.Text,
                PhoneNumber = ContactEntry.Text,
                Pin = PinEntry.Text
            };


            string errorMessage = await new ApiService().CreateAccountAsync(account);

            if (string.IsNullOrEmpty(errorMessage))
            {
                // ? Save the newly created phone number securely
                await SecureStorage.SetAsync("selectedPhoneNumber", account.PhoneNumber);


                await DisplayAlert("Success", "Account created! Enter your PIN to log in.", "OK");

                // ? Navigate to MainPage (PIN entry screen)
                Application.Current.MainPage = new NavigationPage(new MainPage());
            }
            else
            {
                await DisplayAlert("Error", errorMessage, "OK");
            }
        }

        private async void OnBackClicked(object sender, EventArgs e)
        {
            await Navigation.PopAsync();
        }
    }
}
