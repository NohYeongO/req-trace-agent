package demo.web.request;

@Schema(description = "장바구니 상품 추가 요청")
public record CartItemAddRequest(
        @Schema(description = "상품 ID", example = "1")
        @NotNull
        Long productId,

        @Schema(description = "수량")
        @NotNull @Min(1) @Max(99)
        Integer quantity
) {
}
