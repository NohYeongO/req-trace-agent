package demo.entity;

@Entity
@Table(name = "carts")
public class Cart extends BaseEntity {
    @Column(nullable = false)
    private Long accountId;

    @OneToMany(mappedBy = "cart")
    private List<CartItem> items = new ArrayList<>();
}
