package demo.entity;

@Entity
@Table(name = "cart_items", uniqueConstraints = {
        @UniqueConstraint(name = "uk_cart_product", columnNames = {"cart_id", "product_id"})
})
public class CartItem extends BaseEntity {
    private static final int MAX = 99;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "cart_id", nullable = false)
    private Cart cart;

    @Column(nullable = false)
    private Long productId;

    private int quantity;

    @Column(length = 40)
    private String memo;   // DDL에는 없는 컬럼

    @Enumerated(EnumType.STRING)
    private ItemStatus status;

    public void change(int q) { int local = q; this.quantity = local; }
}
