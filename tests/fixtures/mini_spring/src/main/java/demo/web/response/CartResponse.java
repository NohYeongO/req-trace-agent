package demo.web.response;

public record CartResponse(Long id, List<CartItemResponse> items, int totalPrice) {
}
