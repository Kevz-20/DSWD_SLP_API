using System;
using System.Collections.Generic;

namespace SME.Models
{
    // Enum for SaleType
    public enum SaleType
    {
        Cash,
        Utang
    }

    public class Sale
    {
        public int Id { get; set; }
        public DateTime Date { get; set; }
        public SaleType SaleType { get; set; }  // Using Enum for SaleType
        public string? CustomerName { get; set; }
        public DateTime? DueDate { get; set; }  // Use DateTime for DueDate
        public string AccountId { get; set; }

        // List of Products sold in the sale
        public List<Product> Products { get; set; } = new List<Product>();
    }

    public class Product
    {
        public string ProductName { get; set; }
        public decimal Quantity { get; set; }
        public decimal Price { get; set; }
    }
}
