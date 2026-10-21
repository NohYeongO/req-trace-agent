package demo.web;

@Tag(name = "Cart", description = "장바구니 API")
@RestController
@RequestMapping("/api/carts")
public class CartController {

    @Operation(summary = "장바구니 상품 추가")
    @PostMapping("/items")
    public ApiResult<CartResponse> addItem(@AuthenticationPrincipal Long accountId,
                                           @RequestBody @Valid CartItemAddRequest request) {
        return null;
    }

    @PatchMapping("/items/{cartItemId}")
    public ApiResult<CartResponse> updateItem(
            @Parameter(description = "장바구니 항목 ID") @PathVariable Long cartItemId,
            @RequestParam(defaultValue = "false") boolean dryRun) {
        return null;
    }
}
