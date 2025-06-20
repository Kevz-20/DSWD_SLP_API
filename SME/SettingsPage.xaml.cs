using System.Text;

namespace SME
{
    public partial class SettingsPage : ContentPage
    {
        public SettingsPage()
        {
            InitializeComponent();
        }

        protected override async void OnAppearing()
        {
            base.OnAppearing();

            string phoneNumber = App.CurrentPhoneNumber;

            if (!string.IsNullOrEmpty(phoneNumber))
            {
                try
                {
                    using (HttpClient client = new HttpClient())
                    {
                        string apiUrl = $"http://10.0.2.2:8000/api/accounts/fullname/{phoneNumber}/";
                        HttpResponseMessage response = await client.GetAsync(apiUrl);

                        if (response.IsSuccessStatusCode)
                        {
                            string json = await response.Content.ReadAsStringAsync();
                            var result = Newtonsoft.Json.Linq.JObject.Parse(json);
                            string fullName = result["full_name"]?.ToString();
                            FullNameLabel.Text = fullName;
                        }
                        else
                        {
                            await DisplayAlert("Error", "Failed to load full name.", "OK");
                        }
                    }
                }
                catch (Exception ex)
                {
                    await DisplayAlert("Error", $"Unable to connect: {ex.Message}", "OK");
                }
            }
        }

        private async void OnChangeFullNameClicked(object sender, EventArgs e)
        {
            string newName = await DisplayPromptAsync(
                "Change Full Name",
                "Enter your new full name:",
                "OK",
                "Cancel",
                "e.g. Maria Santos",
                maxLength: 50,
                keyboard: Keyboard.Text);

            if (!string.IsNullOrWhiteSpace(newName))
            {
                string phoneNumber = App.CurrentPhoneNumber;
                if (string.IsNullOrEmpty(phoneNumber))
                {
                    await DisplayAlert("Error", "Phone number not found.", "OK");
                    return;
                }

                try
                {
                    using (HttpClient client = new HttpClient())
                    {
                        string apiUrl = $"http://10.0.2.2:8000/api/accounts/fullname/update/{phoneNumber}/";

                        var content = new StringContent(
                            Newtonsoft.Json.JsonConvert.SerializeObject(new { full_name = newName }),
                            System.Text.Encoding.UTF8,
                            "application/json");

                        HttpResponseMessage response = await client.PutAsync(apiUrl, content);

                        if (response.IsSuccessStatusCode)
                        {
                            FullNameLabel.Text = newName;
                            await DisplayAlert("Success", "Your full name has been updated.", "OK");
                        }
                        else
                        {
                            string errorMsg = await response.Content.ReadAsStringAsync();
                            await DisplayAlert("Error", $"Failed to update full name: {errorMsg}", "OK");
                        }
                    }
                }
                catch (Exception ex)
                {
                    await DisplayAlert("Error", $"Unable to connect: {ex.Message}", "OK");
                }
            }
        }


        private async void OnChangePinClicked(object sender, EventArgs e)
        {
            string phoneNumber = App.CurrentPhoneNumber;

            // Step 1: Ask for current PIN
            string currentPin = await DisplayPromptAsync("Verify", "Enter your current PIN:", "OK", "Cancel", maxLength: 4, keyboard: Keyboard.Numeric);
            if (string.IsNullOrWhiteSpace(currentPin)) return;

            // Step 2: Ask for new PIN
            string newPin = await DisplayPromptAsync("New PIN", "Enter your new 4-digit PIN:", "OK", "Cancel", maxLength: 4, keyboard: Keyboard.Numeric);
            if (string.IsNullOrWhiteSpace(newPin) || newPin.Length != 4)
            {
                await DisplayAlert("Error", "PIN must be 4 digits.", "OK");
                return;
            }

            try
            {
                using (HttpClient client = new HttpClient())
                {
                    string apiUrl = $"http://10.0.2.2:8000/api/accounts/update-pin/{phoneNumber}/";

                    var content = new StringContent(
                        Newtonsoft.Json.JsonConvert.SerializeObject(new
                        {
                            current_pin = currentPin,
                            new_pin = newPin
                        }),
                        Encoding.UTF8,
                        "application/json");

                    HttpResponseMessage response = await client.PutAsync(apiUrl, content);

                    if (response.IsSuccessStatusCode)
                    {
                        await DisplayAlert("Success", "Your PIN has been updated.", "OK");
                    }
                    else
                    {
                        string error = await response.Content.ReadAsStringAsync();
                        await DisplayAlert("Error", $"Update failed: {error}", "OK");
                    }
                }
            }
            catch (Exception ex)
            {
                await DisplayAlert("Error", $"Failed to connect: {ex.Message}", "OK");
            }
        }


        private async void OnAppThemeClicked(object sender, EventArgs e)
        {
            await DisplayAlert("App Theme", "Theme customization is coming soon.", "OK");
        }

        private async void OnSecurityLockArrowTapped(object sender, EventArgs e)
        {
            await DisplayAlert("Security Lock Info", "Turn this on to require a PIN every time the app opens.", "OK");
        }

        private void OnSecurityLockToggled(object sender, ToggledEventArgs e)
        {
            Preferences.Set("SecurityLockEnabled", e.Value);
        }

        private void OnDueDateReminderToggled(object sender, ToggledEventArgs e)
        {
            Preferences.Set("DueDateReminderEnabled", e.Value);
        }

        private async void OnSwitchAccountClicked(object sender, EventArgs e)
        {
            bool confirm = await DisplayAlert("Switch Account", "Are you sure you want to switch accounts?", "Yes", "Cancel");
            if (confirm)
            {
                // TODO: Clear session or user-specific data
                await DisplayAlert("Account Switched", "You have successfully switched accounts.", "OK");
                await Shell.Current.GoToAsync("//LoginPage");
            }
        }

        private async void OnLogOutClicked(object sender, EventArgs e)
        {
            bool confirm = await DisplayAlert("Log Out", "Do you really want to log out?", "Yes", "Cancel");
            if (confirm)
            {
                // TODO: Clear session, cache, or tokens
                await DisplayAlert("Logged Out", "You have been logged out successfully.", "OK");
                await Shell.Current.GoToAsync("//LoginPage");
            }
        }
    }
}