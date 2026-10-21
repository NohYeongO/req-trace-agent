"""Spring 어노테이션 엔드포인트 분석."""
from agent.spring_endpoints import parse_controller

SRC = '''
package demo;
@RestController
@RequestMapping("/api/orders")
public class OrderController {
    @PostMapping
    public ApiResult<X> createOrder(@RequestBody Req r) { return null; }

    @GetMapping("/{orderId}")
    public ApiResult<X> getOrder(@PathVariable Long orderId) { return null; }

    @PostMapping(value = "/payment", produces = "application/json")
    public ApiResult<X> processPayment() { return null; }

    @GetMapping({"/a", "/b"})
    public void multi() {}

    @RequestMapping(value = "/legacy", method = {RequestMethod.PUT, RequestMethod.DELETE})
    public void legacy() {}
}
'''


def test_parse_controller_combines_prefix_and_methods():
    eps = [(e.method, e.path, e.handler) for e in parse_controller(SRC)]
    assert eps == [
        ("POST", "/api/orders", "OrderController.createOrder"),
        ("GET", "/api/orders/{orderId}", "OrderController.getOrder"),
        ("POST", "/api/orders/payment", "OrderController.processPayment"),
        ("GET", "/api/orders/a", "OrderController.multi"), ("GET", "/api/orders/b", "OrderController.multi"),
        ("PUT", "/api/orders/legacy", "OrderController.legacy"),
        ("DELETE", "/api/orders/legacy", "OrderController.legacy"),
    ]
    assert parse_controller(SRC)[1].line == 9


def test_non_controller_is_ignored():
    assert parse_controller("public class OrderService { @GetMapping void x() {} }") == []
