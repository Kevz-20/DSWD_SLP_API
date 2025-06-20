using SME.Models;

namespace SME
{
    public partial class StockInPage : ContentPage
    {
        public StockInPage()
        {
            InitializeComponent();

            // Set the current date to the Stock-In Date label
            StockInDateLabel.Text = DateTime.Now.ToString("MM/dd/yyyy");

            // Populate CategoryPicker
            CategoryPicker.ItemsSource = new List<string>
            {
                "Beverages",
                "Snacks",
                "Cleaning Supplies",
                "Others"
            };
        }

        private async void OnSaveClicked(object sender, EventArgs e)
        {
            string category = CategoryPicker.SelectedItem?.ToString();  // NEW
            string product = ProductNameEntry.Text;
            string quantity = QuantityEntry.Text;
            string purchasePrice = PurchasePriceEntry.Text;
            string markupRate = MarkupRateEntry.Text;
            string stockInDate = StockInDateLabel.Text;

            // Validation
            if (string.IsNullOrWhiteSpace(category) ||
                string.IsNullOrWhiteSpace(product) ||
                string.IsNullOrWhiteSpace(quantity) ||
                string.IsNullOrWhiteSpace(purchasePrice) ||
                string.IsNullOrWhiteSpace(markupRate) ||
                string.IsNullOrWhiteSpace(stockInDate))
            {
                await DisplayAlert("Incomplete Data", "Please fill in all fields before saving.", "OK");
                return;
            }

            // Convert Quantity, Purchase Price, and Markup Rate to their respective types
            if (!int.TryParse(quantity, out int qty))
            {
                await DisplayAlert("Invalid Data", "Quantity must be a number.", "OK");
                return;
            }

            if (!decimal.TryParse(purchasePrice, out decimal pPrice))
            {
                await DisplayAlert("Invalid Data", "Purchase Price must be a valid decimal number.", "OK");
                return;
            }

            if (!decimal.TryParse(markupRate, out decimal mRate))
            {
                await DisplayAlert("Invalid Data", "Markup Rate must be a valid decimal number.", "OK");
                return;
            }

            // Dummy Product ID for testing
            int productId = 1;

            // Call API
            ApiService apiService = new ApiService();
            var errorMessage = await apiService.StockInAsync(category, product, qty, pPrice, mRate);

            if (string.IsNullOrEmpty(errorMessage))
            {
                await DisplayAlert("Stock In Saved", "Your stock-in record has been successfully saved.", "OK");

                // Clear form
                CategoryPicker.SelectedIndex = -1;
                ProductNameEntry.Text = string.Empty;
                QuantityEntry.Text = string.Empty;
                PurchasePriceEntry.Text = string.Empty;
                MarkupRateEntry.Text = string.Empty;
            }
            else
            {
                await DisplayAlert("Error", errorMessage, "OK");
            }
        }
    }
}
