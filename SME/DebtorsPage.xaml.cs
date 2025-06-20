using System.Collections.ObjectModel;
using SME.Models;

namespace SME;

public partial class DebtorsPage : ContentPage
{
    public ObservableCollection<CustomerDisplay> Customers { get; set; } = new();

    public DebtorsPage()
    {
        InitializeComponent();
        BindingContext = this;
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        var api = new ApiService();
        var customerData = await api.GetCustomersAsync(); // API call

        Customers.Clear();
        foreach (var cust in customerData)
        {
            Customers.Add(new CustomerDisplay
            {
                FullName = $"{cust.FirstName} {cust.LastName}",
                Address = cust.Address,
                ContactNumber = cust.ContactNumber
            });
        }
    }

    private void OnSearchTextChanged(object sender, TextChangedEventArgs e)
    {
        string keyword = e.NewTextValue?.ToLower() ?? "";

        CustomerListView.ItemsSource = Customers
            .Where(c => c.FullName.ToLower().Contains(keyword) ||
                        c.Address.ToLower().Contains(keyword) ||
                        c.ContactNumber.Contains(keyword))
            .ToList();
    }

    private void OnAddDebtorClicked(object sender, EventArgs e)
    {
        // Navigate to your add-debtor page
    }
}

public class CustomerDisplay
{
    public string FullName { get; set; }
    public string Address { get; set; }
    public string ContactNumber { get; set; }
}
