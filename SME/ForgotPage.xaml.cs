using Microsoft.Maui.Controls;

namespace SME
{
    public partial class ForgotPage : ContentPage
    {
        public ForgotPage()
        {
            InitializeComponent();
        }

        // Handle the submit action (e.g., sending an email or phone verification)
        private async void OnSubmitClicked(object sender, EventArgs e)
        {
            // Add your logic for submitting the request here (e.g., send an email or verify phone number)
            await DisplayAlert("PIN Reset Request", "Your request has been submitted. Please check your  phone for further instructions.", "OK");

            // Optionally navigate back to the login page after submission
            await Navigation.PopAsync();
        }
    }
}
