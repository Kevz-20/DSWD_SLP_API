using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Threading.Tasks;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Storage;
using SME.Models;
using static SME.Models.ApiService;

namespace SME
{
    public partial class RecordExpensesPage : ContentPage
    {
        private FileResult? _selectedReceipt;
        private readonly ApiService _apiService = new ApiService();

        public RecordExpensesPage()
        {
            InitializeComponent();

            CategoryPicker.ItemsSource = new List<string>
            {
                "Inventory",
                "Transportation",
                "Utilities",
                "Personal",
                "Others"
            };

            DateLabel.Text = DateTime.Now.ToString("MMMM dd, yyyy");
        }

        private void OnCategoryArrowTapped(object sender, EventArgs e)
        {
            CategoryPicker.Focus();
        }

        private async void OnUploadReceiptTapped(object sender, EventArgs e)
        {
            try
            {
                _selectedReceipt = await FilePicker.PickAsync(new PickOptions
                {
                    PickerTitle = "Select Receipt",
                    FileTypes = FilePickerFileType.Images
                });

                if (_selectedReceipt != null)
                {
                    // ? Display the selected image in the Image control
                    var stream = await _selectedReceipt.OpenReadAsync();
                    SelectedReceiptImage.Source = ImageSource.FromStream(() => stream);

                    // Optional confirmation
                    await DisplayAlert("Receipt Selected", _selectedReceipt.FileName, "OK");
                }
            }
            catch (Exception ex)
            {
                await DisplayAlert("Error", $"Failed to pick file: {ex.Message}", "OK");
            }
        }


        private async void OnSaveExpenseClicked(object sender, EventArgs e)
        {
            var accountId = SessionData.AccountId;
            var amount = decimal.Parse(AmountEntry.Text);
            var category = CategoryPicker.SelectedItem.ToString();
            var description = DescriptionEntry.Text;

            var api = new ApiService();
            var result = await api.UploadExpenseAsync(accountId, amount, category, description, _selectedReceipt);
            await DisplayAlert("Upload Result", result, "OK");
        }


    }
}
