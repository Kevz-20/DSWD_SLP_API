using Newtonsoft.Json;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;

namespace SME
{
    public partial class CustomerDebtDetailsPage : ContentPage
    {
        private int _customerId;

        public CustomerDebtDetailsPage(int customerId, string customerName)
        {
            InitializeComponent();
            _customerId = customerId;
            CustomerNameLabel.Text = customerName;
        }

        protected override async void OnAppearing()
        {
            base.OnAppearing();
            await LoadCustomerDebts();
        }

        private async Task LoadCustomerDebts()
        {
            try
            {
                using var httpClient = new HttpClient();
                var response = await httpClient.GetAsync($"http://10.0.2.2:8000/api/customers/{_customerId}/debts/");

                if (response.IsSuccessStatusCode)
                {
                    var json = await response.Content.ReadAsStringAsync();
                    var debtItems = JsonConvert.DeserializeObject<List<CreditDisplayItem>>(json);

                    DebtListView.ItemsSource = debtItems;
                    decimal total = debtItems.Sum(i =>
                    {
                        if (decimal.TryParse(i.AmountDisplay.Replace("?", ""), out var val)) return val;
                        return 0;
                    });

                    TotalAmountLabel.Text = $"?{total:N2}";
                }
                else
                {
                    await DisplayAlert("Error", "Failed to load debt details.", "OK");
                }
            }
            catch
            {
                await DisplayAlert("Error", "Could not connect to server.", "OK");
            }
        }
    }

    public class CreditDisplayItem
    {
        [JsonProperty("credit_date")]
        public string CreditDate { get; set; }

        [JsonProperty("due_date")]
        public string DueDate { get; set; }

        [JsonProperty("amount_display")]
        public string AmountDisplay { get; set; }

        [JsonProperty("product_summary")]
        public string ProductSummary { get; set; }

        [JsonProperty("status_label")]
        public string StatusLabel { get; set; }

        [JsonProperty("status_color")]
        public string StatusColor { get; set; }

        [JsonProperty("show_add_payment")]
        public bool ShowAddPayment { get; set; }
    }

}
