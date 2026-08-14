import { api } from "./client";

export interface ProductRead {
  id: string;
  name: string;
  description: string | null;
  // Computed by the server (join/count), not a stored column.
  repository_count: number;
  created_at: string;
}

export interface ProductCreate {
  name: string;
  description?: string | null;
}

export interface ProductUpdate {
  name: string;
  description?: string | null;
}

export function listProducts(): Promise<ProductRead[]> {
  return api.get<ProductRead[]>("/products");
}

export function getProduct(id: string): Promise<ProductRead> {
  return api.get<ProductRead>(`/products/${encodeURIComponent(id)}`);
}

export function createProduct(payload: ProductCreate): Promise<ProductRead> {
  return api.post<ProductRead>("/products", payload);
}

export function updateProduct(id: string, payload: ProductUpdate): Promise<ProductRead> {
  return api.put<ProductRead>(`/products/${encodeURIComponent(id)}`, payload);
}

// Ungroups member repositories (product_id -> null) rather than blocking —
// a Product is purely organizational, see the Product model's docstring.
export function deleteProduct(id: string): Promise<void> {
  return api.delete<void>(`/products/${encodeURIComponent(id)}`);
}
