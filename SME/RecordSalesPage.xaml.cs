using Microsoft.Maui.Controls;
using Newtonsoft.Json;
using PdfSharpCore.Charting;
using SME.Models;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;

namespace SME
{
    public partial class RecordSalesPage : ContentPage
    {
        private bool isUtang = false;
        private bool awaitingPaymentChoice = true;
        private string? selectedPaymentMethod = null;

        private List<InventoryItemResponse> _inventory = new();
        private List<CustomerResponse> _customers = new();
        private InventoryItemResponse _selectedProduct;
        private CustomerResponse _selectedCustomer;

        public RecordSalesPage()
        {
            InitializeComponent();
            DateLabel.Text = DateTime.Now.ToString("MMMM dd, yyyy");
            SetPaymentMethod(false);
        }

        protected override async void OnAppearing()
        {
            base.OnAppearing();
            var api = new ApiService();
            _inventory = await api.GetInventoryAsync();
            _customers = await api.GetCustomersAsync();
            ResetForm();
        }

        private void SetPaymentMethod(bool isUtang)
        {
            this.isUtang = isUtang;
            UtangFields.IsVisible = isUtang;
            awaitingPaymentChoice = false;

            CashButton.BackgroundColor = isUtang ? Color.FromArgb("#2B1A73") : Color.FromArgb("#5A189A");
            UtangButton.BackgroundColor = isUtang ? Color.FromArgb("#5A189A") : Color.FromArgb("#2B1A73");
        }

        private void OnCashClicked(object sender, EventArgs e)
        {
            selectedPaymentMethod = "Cash";
            SetPaymentMethod(false);
            _ = SaveSales();
        }

        private void OnUtangClicked(object sender, EventArgs e)
        {
            selectedPaymentMethod = "Utang";
            SetPaymentMethod(true);
            UtangFields.IsVisible = true;
            CustomerRow.IsVisible = true;
        }

        private void OnAddAnotherSaleClicked(object sender, EventArgs e)
        {
            var newGroup = CreateNewSaleEntryGroup();
            SalesEntriesLayout.Children.Add(newGroup);
        }

        private Frame CreateStyledFrame(View content)
        {
            return new Frame
            {
                BackgroundColor = Color.FromArgb("#13FFFFFF"),
                CornerRadius = 12,
                Padding = 10,
                HasShadow = false,
                Content = content
            };
        }

        private StackLayout CreateNewSaleEntryGroup()
        {
            var productEntry = new Entry
            {
                Placeholder = "Enter Product Name",
                TextColor = Colors.White,
                PlaceholderColor = Colors.White,
                BackgroundColor = Colors.Transparent
            };
            productEntry.TextChanged += OnProductNameChanged;

            var quantityEntry = new Entry
            {
                Placeholder = "Enter Quantity",
                TextColor = Colors.White,
                PlaceholderColor = Colors.White,
                Keyboard = Keyboard.Numeric,
                BackgroundColor = Colors.Transparent
            };
            quantityEntry.TextChanged += OnQuantityChanged;

            var priceEntry = new Entry
            {
                Placeholder = "Selling Price",
                TextColor = Colors.White,
                PlaceholderColor = Colors.White,
                Keyboard = Keyboard.Numeric,
                BackgroundColor = Colors.Transparent
            };
            priceEntry.TextChanged += OnSellingPriceChanged;

            var stack = new StackLayout { Spacing = 10 };
            stack.Children.Add(CreateStyledFrame(productEntry));
            stack.Children.Add(CreateStyledFrame(quantityEntry));
            stack.Children.Add(CreateStyledFrame(priceEntry));

            return stack;
        }

        private async Task SaveSales()
        {
            bool hasErrors = false;

            if (isUtang && _selectedCustomer == null)
            {
                await DisplayAlert("Error", "Please select a customer for utang.", "OK");
                return;
            }

            var saleItems = new List<object>();

            foreach (var group in SalesEntriesLayout.Children.OfType<StackLayout>())
            {
                var frames = group.Children.OfType<Frame>().ToList();
                if (frames.Count < 3) continue;

                var productEntry = frames[0].Content as Entry;
                var quantityEntry = frames[1].Content as Entry;
                var priceEntry = frames[2].Content as Entry;

                string product = productEntry?.Text?.Trim();
                string quantityText = quantityEntry?.Text?.Trim();
                string priceText = priceEntry?.Text?.Trim();

                if (string.IsNullOrWhiteSpace(product) ||
                    !decimal.TryParse(quantityText, out decimal quantity) || quantity <= 0 ||
                    !decimal.TryParse(priceText, out decimal price) || price <= 0)
                {
                    hasErrors = true;
                    continue;
                }

                var matchedProduct = _inventory.FirstOrDefault(p => p.ProductName == product);
                if (matchedProduct == null)
                {
                    hasErrors = true;
                    continue;
                }

                saleItems.Add(new
                {
                    product_id = matchedProduct.Id,
                    quantity = (int)quantity,
                    amount = price * quantity
                });
            }

            if (!saleItems.Any())
            {
                await DisplayAlert("Error", "No valid items to submit.", "OK");
                return;
            }

            var payload = new
            {
                account = ApiService.SessionData.AccountId,
                payment_type = isUtang ? "utang" : "cash",
                customer_id = isUtang ? _selectedCustomer?.Id : (int?)null,
                due_date = isUtang ? DueDatePicker.Date.ToString("yyyy-MM-dd") : null,
                items = saleItems
            };


            var json = JsonConvert.SerializeObject(payload);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var httpClient = new HttpClient();
            var response = await httpClient.PostAsync("http://10.0.2.2:8000/api/submit-sale/", content);

            if (response.IsSuccessStatusCode)
            {
                await DisplayAlert("Success", hasErrors ? "Some items were skipped due to errors." : "All sales saved successfully!", "OK");
                ResetForm();
            }
            else
            {
                var error = await response.Content.ReadAsStringAsync();
                await DisplayAlert("Error", $"Failed to save sales: {error}", "OK");
            }
        }



        private void ResetForm()
        {
            SalesEntriesLayout.Children.Clear();
            SalesEntriesLayout.Children.Add(CreateNewSaleEntryGroup());

            CustomerNameEntry.Text = "";
            DueDatePicker.Date = DateTime.Today;
            AddCustomerEntry.Text = "";
            CustomerSuggestions.IsVisible = false;
            AddCustomerEntry.IsVisible = true;

            OrderTotalLabel.Text = "Order Total: ₱0.00";
            awaitingPaymentChoice = true;
            selectedPaymentMethod = null;
            SetPaymentMethod(false);
            PaymentOptionsLayout.IsVisible = false;
            UtangFields.IsVisible = false;
        }

        private void OnProductNameChanged(object sender, TextChangedEventArgs e)
        {
            string keyword = e.NewTextValue?.ToLower() ?? "";
            var filtered = _inventory
                .Where(p => p.ProductName.ToLower().Contains(keyword))
                .ToList();

            ProductSuggestions.ItemsSource = filtered;
            ProductSuggestions.IsVisible = filtered.Any();
        }

        private void OnCustomerNameChanged(object sender, TextChangedEventArgs e)
        {
            string keyword = e.NewTextValue?.ToLower() ?? "";
            var filtered = _customers
                .Where(c => c.FullName.ToLower().Contains(keyword))
                .ToList();

            CustomerSuggestions.ItemsSource = filtered;
            CustomerSuggestions.IsVisible = filtered.Any();
            AddCustomerEntry.IsVisible = true;
        }

        private void OnCustomerSelected(object sender, SelectionChangedEventArgs e)
        {
            if (e.CurrentSelection.FirstOrDefault() is CustomerResponse selected)
            {
                _selectedCustomer = selected;
                CustomerNameEntry.Text = selected.FullName;
                CustomerSuggestions.IsVisible = false;
                AddCustomerEntry.IsVisible = true;
            }
        }

        private void OnQuantityChanged(object sender, TextChangedEventArgs e) => CalculateOrderTotal();
        private void OnSellingPriceChanged(object sender, TextChangedEventArgs e) => CalculateOrderTotal();

        private void CalculateOrderTotal()
        {
            decimal total = 0;

            foreach (var group in SalesEntriesLayout.Children.OfType<StackLayout>())
            {
                var frames = group.Children.OfType<Frame>().ToList();
                if (frames.Count < 3) continue;

                var quantityEntry = frames[1].Content as Entry;
                var priceEntry = frames[2].Content as Entry;

                if (decimal.TryParse(quantityEntry?.Text, out decimal qty) &&
                    decimal.TryParse(priceEntry?.Text, out decimal price))
                {
                    total += qty * price;
                }
            }

            OrderTotalLabel.Text = $"Order Total: ₱{total:N2}";
        }

        private async void OnSaveClicked(object sender, EventArgs e)
        {
            if (selectedPaymentMethod == null)
            {
                selectedPaymentMethod = await DisplayActionSheet("Select Payment Method", "Cancel", null, "Cash", "Utang");

                if (selectedPaymentMethod == "Cancel" || string.IsNullOrEmpty(selectedPaymentMethod))
                {
                    selectedPaymentMethod = null;
                    return;
                }

                SetPaymentMethod(selectedPaymentMethod == "Utang");

                if (selectedPaymentMethod == "Utang")
                {
                    UtangFields.IsVisible = true;
                    CustomerRow.IsVisible = true;
                }
            }

            if (selectedPaymentMethod == "Utang")
            {
                bool filled = await PromptUtangDetails();
                if (!filled)
                {
                    await DisplayAlert("Missing Info", "Customer name and due date are required.", "OK");
                    return;
                }
            }

            await SaveSales();
            selectedPaymentMethod = null;
        }

        private async Task<bool> PromptUtangDetails()
        {
            string customer = CustomerNameEntry.Text?.Trim();
            string dueDate = DueDatePicker.Date.ToString("yyyy-MM-dd");

            if (!string.IsNullOrWhiteSpace(customer) && !string.IsNullOrWhiteSpace(dueDate))
                return true;

            await DisplayAlert("Incomplete", "Please enter customer's name and due date.", "OK");
            return false;
        }

        private void OnAddNewCustomerClicked(object sender, EventArgs e)
        {
            CustomerPopup.IsVisible = true;
        }

        private async void OnSaveCustomerClicked(object sender, EventArgs e)
        {
            var customerData = new
            {
                first_name = FirstNameEntry.Text,
                last_name = LastNameEntry.Text,
                contact_num = ContactNumberEntry.Text,
                address = AddressEntry.Text,
                account = ApiService.SessionData.AccountId
            };

            var json = JsonConvert.SerializeObject(customerData);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            var httpClient = new HttpClient();
            var response = await httpClient.PostAsync("http://10.0.2.2:8000/api/customers/add/", content);

            if (response.IsSuccessStatusCode)
            {
                await DisplayAlert("Success", "Customer added!", "OK");
                CustomerPopup.IsVisible = false;
                AddCustomerEntry.Text = $"{customerData.first_name} {customerData.last_name}";
            }
            else
            {
                await DisplayAlert("Error", "Failed to add customer.", "OK");
            }
        }

        private void OnCancelCustomerPopup(object sender, EventArgs e)
        {
            CustomerPopup.IsVisible = false;
        }

        private void OnProductSelected(object sender, SelectionChangedEventArgs e)
        {
            if (e.CurrentSelection.Count > 0 && e.CurrentSelection[0] is InventoryItemResponse selected)
            {
                _selectedProduct = selected;

                var currentGroup = SalesEntriesLayout.Children.LastOrDefault() as StackLayout;
                if (currentGroup != null)
                {
                    var productEntry = ((Frame)currentGroup.Children[0]).Content as Entry;
                    var priceEntry = ((Frame)currentGroup.Children[2]).Content as Entry;

                    if (productEntry != null) productEntry.Text = selected.ProductName;
                    if (priceEntry != null) priceEntry.Text = selected.SellingPrice.ToString("F2");
                }

                ProductSuggestions.IsVisible = false;
                ProductSuggestions.SelectedItem = null;
                CalculateOrderTotal();
            }
        }
    }
}
