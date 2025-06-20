using System;
using System.Net.Http;
using System.Text;
using System.Threading.Tasks;
using Newtonsoft.Json;
using SME.Models;
using System.Collections.Generic;
using System.Net.Http.Json;
using System.Text.Json.Serialization;
using System.Net.Http.Headers;
using Microsoft.Maui;

namespace SME.Models
{
    public class ApiService
    {
        private readonly HttpClient _httpClient;

        private static readonly string BaseUrl = "http://10.0.2.2:8000/api/accounts/";

        public ApiService()
        {
            _httpClient = new HttpClient();
        }

        // ✅ GET Inventory from Django REST API
        public async Task<List<InventoryItemResponse>> GetInventoryAsync()
        {
            try
            {
                string url = $"http://10.0.2.2:8000/api/inventory/?account={SessionData.AccountId}";
                var response = await _httpClient.GetAsync(url);
                if (!response.IsSuccessStatusCode)
                    return new List<InventoryItemResponse>();

                string json = await response.Content.ReadAsStringAsync();
                return JsonConvert.DeserializeObject<List<InventoryItemResponse>>(json) ?? new List<InventoryItemResponse>();

            }
            catch (Exception ex)
            {
                Console.WriteLine($"[DOTNET] Error fetching inventory: {ex.Message}");
                return new List<InventoryItemResponse>(); // return empty list on error
            }
        }

        // ✅ POST: Create Account
        public async Task<string?> CreateAccountAsync(Account account)
        {
            try
            {
                var accountData = new
                {
                    first_name = account.FirstName,
                    middle_name = account.MiddleName,
                    last_name = account.LastName,
                    phone_number = account.PhoneNumber,
                    pin = account.Pin
                };

                string jsonData = JsonConvert.SerializeObject(accountData);
                StringContent content = new StringContent(jsonData, Encoding.UTF8, "application/json");

                HttpResponseMessage response = await _httpClient.PostAsync($"{BaseUrl}create/", content);

                if (response.IsSuccessStatusCode)
                    return null;

                string responseContent = await response.Content.ReadAsStringAsync();
                var errorObj = JsonConvert.DeserializeObject<Dictionary<string, string>>(responseContent);
                if (errorObj != null && errorObj.ContainsKey("error"))
                    return errorObj["error"];

                return "Phone Number Already in use !!!";
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[DOTNET] Error creating account: {ex.Message}");
                return "Unable to connect to the server.";
            }
        }

        public class AccountLoginResponse
        {
            public int id { get; set; }
            public required string first_name { get; set; }
            public required string last_name { get; set; }
            public required string phone_number { get; set; }
            public required string pin { get; set; }
            public required string middle_name { get; set; }
        }

        public static class SessionData
        {
            public static int AccountId { get; set; }
        }
        // ✅ POST: Login
        public async Task<string?> LoginAsync(string phoneNumber, string pin)
        {
            var loginData = new
            {
                phone_number = phoneNumber.Trim(),
                pin = pin.Trim()
            };

            var json = JsonConvert.SerializeObject(loginData);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            try
            {
                var response = await _httpClient.PostAsync($"{BaseUrl}login/", content);

                if (!response.IsSuccessStatusCode)
                {
                    string error = await response.Content.ReadAsStringAsync();
                    return $"Login failed: {error}";
                }

                string result = await response.Content.ReadAsStringAsync();
                var account = JsonConvert.DeserializeObject<AccountLoginResponse>(result);

                SessionData.AccountId = account.id;
                Console.WriteLine("✅ Logged in as Account ID: " + SessionData.AccountId);

                return null;
            }
            catch (Exception ex)
            {
                return $"An error occurred: {ex.Message}";
            }
        }



        // ✅ GET: Get Account by Phone
        public async Task<Account?> GetAccountAsync(string phoneNumber)
        {
            try
            {
                HttpResponseMessage response = await _httpClient.GetAsync($"{BaseUrl}{phoneNumber}/");

                if (response.IsSuccessStatusCode)
                {
                    string jsonResponse = await response.Content.ReadAsStringAsync();
                    return JsonConvert.DeserializeObject<Account>(jsonResponse);
                }

                return null;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[DOTNET] Error fetching account: {ex.Message}");
                return null;
            }
        }

        // ✅ POST: Stock In
        public async Task<string?> StockInAsync(string category, string productName, int quantity, decimal purchasePrice, decimal markupRate)
        {
            var stockInData = new
            {
                category = category,
                product_name = productName,
                quantity = quantity,
                purchase_price = purchasePrice,
                markup_rate = markupRate,
                account = SessionData.AccountId
            };

            var json = JsonConvert.SerializeObject(stockInData);
            var content = new StringContent(json, Encoding.UTF8, "application/json");

            try
            {
                var response = await _httpClient.PostAsync("http://10.0.2.2:8000/api/add-product-stockin/", content);

                if (response.IsSuccessStatusCode)
                    return null;

                string responseContent = await response.Content.ReadAsStringAsync();
                return $"Failed to save stock-in. Server Response: {responseContent}";
            }
            catch (Exception ex)
            {
                return $"An error occurred: {ex.Message}";
            }
        }

        // ✅ POST: Reset PIN
        public async Task<string> ResetPinAsync(string phoneNumber)
        {
            try
            {
                var resetData = new { phone = phoneNumber };
                string jsonData = JsonConvert.SerializeObject(resetData);
                StringContent content = new StringContent(jsonData, Encoding.UTF8, "application/json");

                HttpResponseMessage response = await _httpClient.PostAsync($"{BaseUrl}reset_pin/", content);

                if (response.IsSuccessStatusCode)
                    return "PIN has been sent to your phone number.";

                string responseContent = await response.Content.ReadAsStringAsync();
                return $"Failed to send PIN. {responseContent}";
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[DOTNET] Error resetting PIN: {ex.Message}");
                return "Unable to connect to the server.";
            }
        }

        // ✅ POST: Send PIN
        public async Task<string> SendPinAsync(string phoneNumber)
        {
            try
            {
                var pinRequestData = new { phone_number = phoneNumber };
                string jsonData = JsonConvert.SerializeObject(pinRequestData);
                StringContent content = new StringContent(jsonData, Encoding.UTF8, "application/json");

                HttpResponseMessage response = await _httpClient.PostAsync($"{BaseUrl}send-pin/", content);

                if (response.IsSuccessStatusCode)
                    return "PIN has been sent. Please check your phone.";

                string errorContent = await response.Content.ReadAsStringAsync();
                return $"Error: {errorContent}";
            }
            catch (Exception ex)
            {
                return $"Failed to send PIN: {ex.Message}";
            }
        }


        public async Task<string> UploadExpenseAsync(
            int accountId,
            decimal amount,
            string category,
            string description,
            FileResult receiptFile = null)
        {
            try
            {
                var requestContent = new MultipartFormDataContent();

                // Add form fields
                requestContent.Add(new StringContent(accountId.ToString()), "account");
                requestContent.Add(new StringContent(amount.ToString()), "amount");
                requestContent.Add(new StringContent(category), "category");
                requestContent.Add(new StringContent(description), "description");

                // Add optional receipt image
                if (receiptFile != null)
                {
                    using var stream = await receiptFile.OpenReadAsync();

                    var fileExtension = Path.GetExtension(receiptFile.FileName).ToLower();
                    var mimeType = fileExtension switch
                    {
                        ".png" => "image/png",
                        ".jpg" => "image/jpeg",
                        ".jpeg" => "image/jpeg",
                        ".gif" => "image/gif",
                        _ => "application/octet-stream"
                    };

                    var streamContent = new StreamContent(stream);
                    streamContent.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue(mimeType);

                    requestContent.Add(streamContent, "receipt_path", receiptFile.FileName);
                }

                // Send POST request to Django API
                var response = await _httpClient.PostAsync("http://10.0.2.2:8000/api/upload-expense/", requestContent);
                var responseString = await response.Content.ReadAsStringAsync();

                if (response.IsSuccessStatusCode)
                {
                    return "Expense uploaded successfully!";
                }
                else
                {
                    Console.WriteLine("❌ Upload failed. Response: " + responseString);
                    return $"Error: {response.StatusCode} - {responseString}";
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine("❌ Exception during upload: " + ex.Message);
                return $"Exception: {ex.Message}";
            }
        }

        public async Task<List<CustomerResponse>> GetCustomersAsync()
        {
            try
            {
                string url = $"http://10.0.2.2:8000/api/customers/?account={SessionData.AccountId}";
                var response = await _httpClient.GetAsync(url);

                if (!response.IsSuccessStatusCode)
                    return new List<CustomerResponse>();

                var json = await response.Content.ReadAsStringAsync();
                return JsonConvert.DeserializeObject<List<CustomerResponse>>(json) ?? new List<CustomerResponse>();
            }
            catch (Exception ex)
            {
                Console.WriteLine("❌ Error fetching customers: " + ex.Message);
                return new List<CustomerResponse>();
            }
        }


    }

    // ✅ DTO: Matches Django API response (snake_case to PascalCase with mapping)
    public class InventoryItemResponse
    {

        [JsonProperty("id")]
        public int Id { get; set; }

        [JsonProperty("product_name")]
        public string ProductName { get; set; } = string.Empty;

        [JsonProperty("category")]
        public string Category { get; set; } = string.Empty;

        [JsonProperty("quantity")]
        public int Quantity { get; set; }

        [JsonProperty("selling_price")]
        public decimal SellingPrice { get; set; }

        [JsonProperty("purchase_price")]
        public int PurchasePrice { get; set; }

        [JsonProperty("markup_rate")]
        public decimal MarkupRate { get; set; }
    }

    public class CustomerResponse
    {

        [JsonProperty("id")]
        public int Id { get; set; }

        [JsonProperty("first_name")]
        public string FirstName { get; set; }

        [JsonProperty("last_name")]
        public string LastName { get; set; }

        [JsonProperty("contact_num")]
        public string ContactNumber { get; set; }

        [JsonProperty("address")]
        public string Address { get; set; }

        public string FullName => $"{FirstName} {LastName}";
    }

}
