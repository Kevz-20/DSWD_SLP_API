using System;
using System.Collections.ObjectModel;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.Maui.Controls;
using SME.Models;
using System.Text.Json.Serialization;
using Newtonsoft.Json;

namespace SME
{
    public partial class ManageInventoryPage : ContentPage
    {
        public ObservableCollection<InventoryItem> InventoryItems { get; set; } = new();

        public ManageInventoryPage()
        {
            InitializeComponent();
            BindingContext = this;
            _ = LoadInventoryAsync();  // Starts the async method without blocking
        }

        private async Task LoadInventoryAsync()
        {
            try
            {
                var api = new ApiService();
                var items = await api.GetInventoryAsync();  

                InventoryItems.Clear();

                foreach (var item in items)
                {
                    InventoryItems.Add(new InventoryItem
                    {
                        ProductName = item.ProductName,
                        Stock = item.Quantity,
                        CostTo = item.PurchasePrice,
                        Category = item.Category,
                        SellingPrice = item.SellingPrice

                    });

                }

                InventoryListView.ItemsSource = InventoryItems;
            }
            catch (Exception ex)
            {
                await DisplayAlert("Error", $"Failed to load inventory: {ex.Message}", "OK");
            }
        }

        private void OnSearchTextChanged(object sender, TextChangedEventArgs e)
        {
            string searchQuery = e.NewTextValue?.ToLower() ?? "";

            InventoryListView.ItemsSource = string.IsNullOrWhiteSpace(searchQuery)
                ? InventoryItems
                : InventoryItems.Where(item => item.ProductName.ToLower().Contains(searchQuery)).ToList();
        }

        private async void OnEditItemClicked(object sender, EventArgs e)
        {
            var button = sender as ImageButton;
            var item = button?.BindingContext as InventoryItem;

            if (item != null)
            {
                await DisplayAlert("Edit", $"Editing: {item.ProductName}", "OK");
                // You can navigate to an edit form here
            }
        }

        private async void OnDeleteItemClicked(object sender, EventArgs e)
        {
            var button = sender as ImageButton;
            var item = button?.BindingContext as InventoryItem;

            if (item != null)
            {
                bool confirm = await DisplayAlert("Confirm Delete", $"Are you sure you want to delete {item.ProductName}?", "Yes", "No");
                if (confirm)
                {
                    InventoryItems.Remove(item);
                    await DisplayAlert("Deleted", $"{item.ProductName} was removed.", "OK");
                    // Optionally call API to delete it from backend
                }
            }
        }
    }

    public class InventoryItem
    {
        public string ProductName { get; set; } = string.Empty;
        public int Stock { get; set; }
        public string Category { get; set; } = string.Empty;
        public decimal CostTo { get; set; }
        public decimal SellingPrice { get; set; }
        public bool IsLowStock => Stock < 5;
    }

 
}
